#include "client.h"

#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <sstream>

namespace raven {

static double seconds() {
    return std::chrono::duration<double>(std::chrono::steady_clock::now().time_since_epoch()).count();
}

static bool ref_of(const std::string& s, FieldRef& r) {
    return std::sscanf(s.c_str(), "%d:%d", &r.channel, &r.field) == 2;
}

static std::string ref_text(FieldRef r) {
    return std::to_string(r.channel) + ":" + std::to_string(r.field);
}

void Client::tick() {
    if (!sock_.valid()) {
        has_desc_ = false;
        if (seconds() < next_try_) return;
        next_try_ = seconds() + 1.0;
        if (!sock_.connect(host_, port_)) return;
        watch_.clear();
        links_.clear();
        next_links_ = 0;
        send("hello");
    }
    std::vector<std::string> lines;
    if (!sock_.receive(lines, 0)) last_error = "connexion perdue";
    for (const std::string& l : lines) handle(l);
    // L'etat des liaisons est demande une fois par seconde : il sert a tenir
    // la zone fixe a jour, y compris pour les liaisons que l'on ne regarde pas.
    if (has_desc_ && seconds() >= next_links_) {
        next_links_ = seconds() + 1.0;
        send("links");
    }
}

const LinkInfo* Client::current_link() const {
    for (const LinkInfo& l : links_)
        if (l.current) return &l;
    return links_.empty() ? nullptr : &links_.front();
}

std::string Client::channel_direction(int channel) const {
    const LinkInfo* l = current_link();
    if (!l) return std::string();
    auto it = l->channels.find(channel);
    return it == l->channels.end() ? std::string() : it->second.first;
}

void Client::use_link(const std::string& name) {
    // Les valeurs, traces et evenements sont indexes par (canal, champ) : d'une
    // liaison a l'autre, les memes indices designent d'autres champs. Tout
     // repartir de zero est la seule lecture honnete.
    values.clear();
    traces.clear();
    events.clear();
    sentinel_last.clear();
    watch_.clear();
    send("use " + name);
}

void Client::send(const std::string& cmd) {
    if (sock_.valid()) sock_.send(cmd + "\n");
}

void Client::set_watch(const std::vector<FieldRef>& refs) {
    if (refs == watch_ || !ready()) return;
    watch_ = refs;
    std::string cmd = "watch";
    for (const FieldRef& r : refs) cmd += " " + ref_text(r);
    send(cmd);
}

void Client::handle(const std::string& line) {
    if (in_desc_) {
        if (line == "desc_end") {
            in_desc_ = false;
            std::string err;
            has_desc_ = desc_.parse(desc_text_, err);
            if (!has_desc_) last_error = "descripteur recu invalide : " + err;
            values.clear();
            traces.clear();
        } else {
            desc_text_ += line + "\n";
        }
        return;
    }
    std::istringstream in(line);
    std::string tag, a;
    in >> tag;
    FieldRef r;
    if (tag == "link") {
        // Premiere ligne d'un lot : on reconstruit la liste, puis on la
        // publie d'un coup, pour que l'IHM ne voie jamais un etat a moitie lu.
        LinkInfo l;
        in >> l.index >> l.name >> l.state >> l.frames >> l.source;
        std::string rest;
        if (in >> rest) l.current = rest == "*";
        if (l.index == 0) links_building_.clear();
        links_building_.push_back(l);
        links_ = links_building_;
    } else if (tag == "chan") {
        int li = 0, ci = 0;
        std::string dir, name;
        in >> li >> ci >> dir >> name;
        for (LinkInfo& l : links_building_)
            if (l.index == li) l.channels[ci] = std::make_pair(dir == "-" ? "" : dir, name);
        links_ = links_building_;
    } else if (tag == "desc_begin") {
        in_desc_ = true;
        desc_text_.clear();
    } else if (tag == "cfg_begin") {
        in_cfg_ = true;
        rec.clear(); sen.clear(); trc.clear();
        trg_active = false;
    } else if (tag == "cfg_end") {
        in_cfg_ = false;
        for (auto it = traces.begin(); it != traces.end();)
            it = trc.count(it->first) ? std::next(it) : traces.erase(it);
    } else if (in_cfg_ && (tag == "rec" || tag == "sen" || tag == "trc")) {
        in >> a;
        if (ref_of(a, r)) (tag == "rec" ? rec : tag == "sen" ? sen : trc).insert(r);
    } else if (in_cfg_ && tag == "trg") {
        in >> a >> trg_op >> trg_value;
        trg_active = ref_of(a, trg_ref);
    } else if (in_cfg_ && tag == "path") {
        std::getline(in, path);
        if (!path.empty() && path[0] == ' ') path.erase(0, 1);
    } else if (tag == "st") {
        in >> state;
        while (in >> a) {
            const size_t eq = a.find('=');
            const std::string k = a.substr(0, eq), v = a.substr(eq + 1);
            if (k == "msg") {
                std::string rest;
                std::getline(in, rest);
                message = v + rest;
                break;
            }
            const uint64_t n = std::strtoull(v.c_str(), nullptr, 10);
            if (k == "frames") frames = n;
            else if (k == "last") last = n;
            else if (k == "lost") lost = n;
            else if (k == "src") source_ok = n != 0;
            else if (k == "rec") rec_frames = n;
            else if (k == "bytes") rec_bytes = n;
            else if (k == "dropped") dropped = n;
        }
    } else if (tag == "v") {
        in >> a;
        std::string hex;
        in >> hex;
        if (paused || !ref_of(a, r)) return;
        std::vector<unsigned char>& v = values[r];
        v.resize(hex.size() / 2);
        for (size_t i = 0; i < v.size(); ++i)
            v[i] = (unsigned char)std::strtoul(hex.substr(2 * i, 2).c_str(), nullptr, 16);
    } else if (tag == "s") {
        SentinelEvent e;
        in >> a >> e.frame >> e.old_value >> e.new_value >> e.count;
        if (!ref_of(a, e.ref)) return;
        events.push_back(e);
        if (events.size() > kEventLength) events.pop_front();
        sentinel_last[e.ref] = e;
    } else if (tag == "t") {
        uint64_t frame = 0;
        double v = 0;
        in >> a >> frame >> v;
        if (!ref_of(a, r)) return;
        Trace& t = traces[r];
        t.values.push_back(float(v));
        t.last_frame = frame;
        if (t.values.size() > kTraceLength) t.values.pop_front();
    } else if (tag == "err") {
        std::getline(in, last_error);
    }
}

} // namespace raven
