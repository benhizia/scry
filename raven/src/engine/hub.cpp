#include "hub.h"

#include <chrono>
#include <sstream>

#include "sources.h"

namespace raven {

bool load_links(const Ini& ini, const std::string& only, const std::string& default_desc,
                std::vector<LinkConfig>& out, std::string& error) {
    out.clear();
    const std::vector<std::string> sections = ini.sections_with("link.");
    if (sections.empty()) { error = "aucune section [link.<nom>]"; return false; }
    for (const std::string& section : sections) {
        const std::string name = section.substr(5);
        if (!only.empty() && name != only) continue;
        LinkConfig c;
        c.name = name;
        c.desc_path = ini.get(section, "desc", default_desc);
        c.record_path = ini.get(section, "record");
        if (c.desc_path.empty()) {
            error = "[" + section + "] desc manquant, et aucun --desc global";
            return false;
        }
        if (!link_spec(ini, section, c.source, error)) return false;
        out.push_back(c);
    }
    if (out.empty()) {
        error = "liaison inconnue : " + only;
        return false;
    }
    return true;
}

Hub::~Hub() { stop(); }

bool Hub::start(const std::vector<LinkConfig>& configs, std::string& error) {
    // Tout monter avant de demarrer quoi que ce soit : une liaison qui
    // echoue ne doit pas laisser les autres a moitie en route.
    std::vector<std::unique_ptr<Link>> prepared;
    for (const LinkConfig& cfg : configs) {
        std::unique_ptr<Link> l(new Link());
        l->cfg = cfg;
        l->desc.reset(new Descriptor());
        if (!l->desc->load(cfg.desc_path, error)) {
            error = cfg.name + " : " + error;
            return false;
        }
        l->source = make_source(cfg.source, *l->desc);
        if (!l->source) {
            error = cfg.name + " : source inconnue : " + cfg.source;
            return false;
        }
        l->engine.reset(new Engine(*l->desc));
        if (!cfg.record_path.empty()) l->engine->command("path " + cfg.record_path);
        prepared.push_back(std::move(l));
    }

    links_ = std::move(prepared);
    stop_ = false;
    // Un fil d'acquisition par liaison. Elles ne s'attendent pas : une liaison
    // muette ne doit pas retarder celle d'a cote.
    for (std::unique_ptr<Link>& l : links_) {
        Link* p = l.get();
        p->th = std::thread([this, p] {
            while (!stop_.load(std::memory_order_relaxed)) {
                const std::size_t n =
                    p->source->poll([&](const Frame& f) { p->engine->on_frame(f); });
                p->engine->set_source(p->source->connected(), p->source->lost(),
                                      p->source->error());
                if (n == 0) std::this_thread::sleep_for(std::chrono::microseconds(500));
            }
        });
    }
    return true;
}

void Hub::stop() {
    stop_.store(true, std::memory_order_relaxed);
    for (std::unique_ptr<Link>& l : links_)
        if (l->th.joinable()) l->th.join();
    links_.clear();
}

void Hub::stop_all_recordings() {
    for (std::unique_ptr<Link>& l : links_) l->engine->command("stop");
}

std::string Hub::summary() const {
    std::string s;
    for (const std::unique_ptr<Link>& l : links_)
        s += "  " + l->cfg.name + " : " + l->source->describe() + ", " +
             std::to_string(l->desc->channels().size()) + " canaux, trame de " +
             std::to_string(l->desc->frame_size()) + " octets, " + l->cfg.desc_path + "\n";
    return s;
}

std::string Hub::links_block() const {
    std::string s;
    for (std::size_t i = 0; i < links_.size(); ++i) {
        const Link& l = *links_[i];
        s += "link " + std::to_string(i) + " " + l.cfg.name + " " +
             rec_state_name(l.engine->state()) + " " + std::to_string(l.engine->frames()) +
             " " + l.source->describe() + (i == current_ ? " *" : "") + "\n";
    }
    return s;
}

Hub::Link* Hub::selected() {
    return current_ < links_.size() ? links_[current_].get() : nullptr;
}

std::string Hub::command(const std::string& line) {
    std::lock_guard<std::mutex> lock(m_);
    std::istringstream in(line);
    std::string cmd, a;
    in >> cmd;

    if (cmd == "links") return links_block();
    if (cmd == "use") {
        in >> a;
        for (std::size_t i = 0; i < links_.size(); ++i) {
            // Par nom ou par indice : un script prefere l'indice, un humain
            // le nom, et les deux desservent le meme protocole.
            if (links_[i]->cfg.name == a || a == std::to_string(i)) {
                current_ = i;
                Link* l = selected();
                // La reponse rend la main a l'etat de la nouvelle liaison :
                // sans son descripteur, le visualiseur ne saurait rien lire.
                return "ok\n" + l->engine->command("hello");
            }
        }
        return "err liaison inconnue : " + a + "\n" + links_block();
    }
    Link* l = selected();
    if (!l) return "err aucune liaison\n";
    return l->engine->command(line);
}

std::string Hub::updates() {
    std::lock_guard<std::mutex> lock(m_);
    Link* l = selected();
    return l ? l->engine->updates() : std::string();
}

} // namespace raven
