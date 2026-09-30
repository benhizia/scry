#include "engine.h"

#include <cstdio>
#include <cstring>
#include <ctime>
#include <sstream>

namespace raven {

// Au-dela, les evenements les plus anciens sont jetes et comptes : le
// visualiseur ne doit jamais freiner l'acquisition.
static const size_t kMaxQueued = 200000;

const char* rec_state_name(RecState s) {
    switch (s) {
    case RecState::Armed: return "armed";
    case RecState::Recording: return "recording";
    default: return "idle";
    }
}

std::string ref_str(FieldRef r) {
    return std::to_string(r.channel) + ":" + std::to_string(r.field);
}

bool parse_ref(const std::string& s, FieldRef& r) {
    return std::sscanf(s.c_str(), "%d:%d", &r.channel, &r.field) == 2;
}

bool Trigger::eval(const Descriptor& d, const unsigned char* frame) const {
    const FieldDesc* f = d.field(ref);
    const double v = read_number(*f, frame + d.frame_offset(ref));
    if (op == "==") return v == value;
    if (op == "!=") return v != value;
    if (op == "<") return v < value;
    if (op == "<=") return v <= value;
    if (op == ">") return v > value;
    if (op == ">=") return v >= value;
    return false;
}

std::string Trigger::text(const Descriptor& d) const {
    if (!active) return "";
    return d.full_path(ref) + " " + op + " " + format_number(d, *d.field(ref), value);
}

static std::string hex(const unsigned char* p, uint32_t n) {
    static const char digits[] = "0123456789abcdef";
    std::string s(size_t(n) * 2, '0');
    for (uint32_t i = 0; i < n; ++i) {
        s[2 * i] = digits[p[i] >> 4];
        s[2 * i + 1] = digits[p[i] & 15];
    }
    return s;
}

static std::string num(double v) {
    char buf[40];
    std::snprintf(buf, sizeof buf, "%.17g", v);
    return buf;
}

Engine::Engine(const Descriptor& d) : d_(d), latest_(d.frame_size(), 0) {}

RecState Engine::state() const { std::lock_guard<std::mutex> l(m_); return state_; }
uint64_t Engine::frames() const { std::lock_guard<std::mutex> l(m_); return frames_; }

void Engine::set_source(bool connected, uint64_t lost, const std::string& error) {
    std::lock_guard<std::mutex> l(m_);
    src_connected_ = connected;
    src_lost_ = lost;
    src_error_ = error;
}

void Engine::on_frame(const Frame& f) {
    std::lock_guard<std::mutex> l(m_);
    // Le moteur tient une image de toutes les donnees observees. Une trame
    // complete la remplace ; un message reseau ne met a jour que son canal.
    if (f.channel < 0) {
        if (f.size != latest_.size()) { ++malformed_; return; }
        std::memcpy(latest_.data(), f.data, latest_.size());
    } else {
        const ChannelDesc* ch = d_.channel(f.channel);
        if (!ch || f.size != ch->size) { ++malformed_; return; }
        std::memcpy(latest_.data() + ch->frame_offset, f.data, f.size);
    }
    ++frames_;
    last_no_ = f.no;
    const unsigned char* img = latest_.data();
    auto concerned = [&](FieldRef r) { return f.channel < 0 || r.channel == f.channel; };

    // Sentinelles : chaque trame est comparee a la precedente, octet par octet.
    for (auto& kv : sentinels_) {
        if (!concerned(kv.first)) continue;
        const FieldDesc& fd = *d_.field(kv.first);
        const unsigned char* p = img + d_.frame_offset(kv.first);
        Sentinel& s = kv.second;
        if (!s.prev.empty() && std::memcmp(s.prev.data(), p, fd.bytes()) != 0) {
            ++s.count;
            events_.push_back("s " + ref_str(kv.first) + " " + std::to_string(f.no) + " " +
                              num(read_number(fd, s.prev.data())) + " " +
                              num(read_number(fd, p)) + " " + std::to_string(s.count));
        }
        s.prev.assign(p, p + fd.bytes());
    }
    // Traces : une valeur par trame (ou par message du canal), aucune n'est sautee.
    for (const FieldRef& r : trc_)
        if (concerned(r))
            events_.push_back("t " + ref_str(r) + " " + std::to_string(f.no) + " " +
                              num(read_number(*d_.field(r), img + d_.frame_offset(r))));
    while (events_.size() > kMaxQueued) { events_.pop_front(); ++dropped_; }

    if (state_ == RecState::Armed && (!trigger_.active || trigger_.eval(d_, img)))
        start_recording(f);
    // Un enregistrement par trame ou par message : l'image complete des champs
    // choisis, et le canal qui vient d'etre mis a jour.
    if (state_ == RecState::Recording && !writer_.write(f.no, f.t_ns, img, f.channel))
        stop_recording("erreur d'ecriture, enregistrement arrete");
}

void Engine::start_recording(const Frame& f) {
    std::string path = path_;
    const size_t t = path.find("%t");
    if (t != std::string::npos) {
        char stamp[32];
        std::time_t now = std::time(nullptr);
        std::strftime(stamp, sizeof stamp, "%Y%m%d_%H%M%S", std::localtime(&now));
        path.replace(t, 2, stamp);
    }
    std::string err;
    if (!writer_.open(path, d_, std::vector<FieldRef>(rec_.begin(), rec_.end()),
                      trigger_.text(d_), err)) {
        state_ = RecState::Idle;
        message_ = err;
        return;
    }
    state_ = RecState::Recording;
    message_ = "enregistrement depuis la trame " + std::to_string(f.no) + " : " + path;
}

void Engine::stop_recording(const std::string& why) {
    const uint64_t n = writer_.records();
    const std::string path = writer_.path();
    writer_.close();
    state_ = RecState::Idle;
    message_ = why + " : " + std::to_string(n) + " trames dans " + path;
}

std::string Engine::config_block() const {
    std::string s = "cfg_begin\n";
    for (const FieldRef& r : rec_) s += "rec " + ref_str(r) + "\n";
    for (const FieldRef& r : sen_) s += "sen " + ref_str(r) + "\n";
    for (const FieldRef& r : trc_) s += "trc " + ref_str(r) + "\n";
    if (trigger_.active)
        s += "trg " + ref_str(trigger_.ref) + " " + trigger_.op + " " + num(trigger_.value) + "\n";
    s += "path " + path_ + "\ncfg_end\n";
    return s;
}

std::string Engine::status_line() const {
    std::string s = "st ";
    s += rec_state_name(state_);
    s += " frames=" + std::to_string(frames_) + " last=" + std::to_string(last_no_) +
         " lost=" + std::to_string(src_lost_) + " src=" + (src_connected_ ? "1" : "0") +
         " rec=" + std::to_string(writer_.records()) + " bytes=" + std::to_string(writer_.bytes()) +
         " dropped=" + std::to_string(dropped_) + " bad=" + std::to_string(malformed_) + " msg=";
    s += !src_error_.empty() && !src_connected_ ? src_error_ : message_;
    return s + "\n";
}

std::string Engine::command(const std::string& line) {
    std::lock_guard<std::mutex> l(m_);
    std::istringstream in(line);
    std::string cmd, a;
    in >> cmd;
    FieldRef r;
    auto bad_ref = [&]() { return !parse_ref(a, r) || !d_.field(r) || !d_.field(r)->is_leaf(); };
    auto toggle = [&](std::set<FieldRef>& set) -> std::string {
        int on = 0;
        in >> a >> on;
        if (bad_ref()) return "err champ invalide\n";
        if (on) set.insert(r); else set.erase(r);
        return "ok\n" + config_block();
    };

    if (cmd == "hello")
        return "desc_begin\n" + d_.text() + "desc_end\n" + config_block() + status_line();
    if (cmd == "watch") {
        watch_.clear();
        while (in >> a)
            if (!bad_ref()) watch_.push_back(r);
        return "";
    }
    if (cmd == "rec") {
        if (state_ != RecState::Idle) return "err selection figee pendant l'enregistrement\n";
        return toggle(rec_);
    }
    if (cmd == "rec_all") {
        if (state_ != RecState::Idle) return "err selection figee pendant l'enregistrement\n";
        int on = 0;
        in >> on;
        rec_.clear();
        if (on)
            for (const FieldRef& x : d_.leaves()) rec_.insert(x);
        return "ok\n" + config_block();
    }
    if (cmd == "sen") {
        std::string reply = toggle(sen_);
        if (sen_.count(r)) sentinels_[r];
        else sentinels_.erase(r);
        return reply;
    }
    if (cmd == "sen_reset") {
        for (auto& kv : sentinels_) kv.second.count = 0;
        return "ok\n";
    }
    if (cmd == "trc") return toggle(trc_);
    if (cmd == "trg") {
        in >> a;
        if (a == "off") { trigger_.active = false; return "ok\n" + config_block(); }
        Trigger t;
        in >> t.op >> t.value;
        if (bad_ref() || in.fail()) return "err declencheur invalide\n";
        static const char* ops[] = {"==", "!=", "<", "<=", ">", ">="};
        bool known = false;
        for (const char* o : ops) known = known || t.op == o;
        if (!known) return "err operateur inconnu\n";
        t.ref = r;
        t.active = true;
        trigger_ = t;
        return "ok\n" + config_block();
    }
    if (cmd == "path") {
        std::getline(in, a);
        const size_t i = a.find_first_not_of(' ');
        if (i == std::string::npos) return "err chemin vide\n";
        path_ = a.substr(i);
        return "ok\n" + config_block();
    }
    if (cmd == "arm") {
        if (state_ != RecState::Idle) return "err deja arme ou en cours\n";
        if (rec_.empty()) return "err aucun champ a enregistrer\n";
        state_ = RecState::Armed;
        message_ = trigger_.active ? "arme, en attente de : " + trigger_.text(d_)
                                   : "arme : demarrage a la prochaine trame";
        return "ok\n";
    }
    if (cmd == "stop") {
        if (state_ == RecState::Recording) stop_recording("arrete");
        else if (state_ == RecState::Armed) { state_ = RecState::Idle; message_ = "desarme"; }
        return "ok\n";
    }
    return "err commande inconnue : " + cmd + "\n";
}

std::string Engine::updates() {
    std::lock_guard<std::mutex> l(m_);
    std::string out = status_line();
    for (const FieldRef& r : watch_)
        out += "v " + ref_str(r) + " " + hex(latest_.data() + d_.frame_offset(r), d_.field(r)->bytes()) + "\n";
    for (const std::string& e : events_) out += e + "\n";
    events_.clear();
    return out;
}

} // namespace raven
