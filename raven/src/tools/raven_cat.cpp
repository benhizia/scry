// raven-cat : relit un .rvn et l'exporte en CSV, enums en texte.
//
//   raven-cat fichier.rvn [--info]
#include <cstdio>
#include <string>
#include <vector>

#include "raven/rvn.h"

using namespace raven;

int main(int argc, char** argv) {
    if (argc < 2) { std::printf("usage : raven-cat <fichier.rvn> [--info]\n"); return 2; }
    RvnReader r;
    std::string err;
    if (!r.open(argv[1], err)) { std::fprintf(stderr, "%s\n", err.c_str()); return 1; }
    const Descriptor& d = r.descriptor();
    if (argc > 2 && std::string(argv[2]) == "--info") {
        std::printf("trames : %llu\ndeclencheur : %s\nchamps :\n", (unsigned long long)r.count(),
                    r.trigger().c_str());
        for (const FieldRef& f : r.selection()) std::printf("  %s\n", d.full_path(f).c_str());
        return 0;
    }
    std::printf("frame,t_ns,channel,dir");
    for (const FieldRef& f : r.selection()) {
        const FieldDesc& fd = *d.field(f);
        for (uint32_t i = 0; i < fd.count; ++i)
            fd.count > 1 ? std::printf(",%s[%u]", d.full_path(f).c_str(), i)
                         : std::printf(",%s", d.full_path(f).c_str());
    }
    std::printf("\n");
    uint64_t no, t;
    std::vector<const unsigned char*> fields;
    for (uint64_t n = 0; r.read(n, no, t, fields); ++n) {
        const ChannelDesc* ch = d.channel(r.last_channel());
        // 'dir' est vide hors relais : une source qui observe sans s'interposer
        // n'a pas de sens a declarer.
        std::printf("%llu,%llu,%s,%s", (unsigned long long)no, (unsigned long long)t,
                    ch ? ch->name.c_str() : "*", direction_name(r.last_direction()));
        for (size_t k = 0; k < fields.size(); ++k) {
            const FieldDesc& fd = *d.field(r.selection()[k]);
            for (uint32_t i = 0; i < fd.count; ++i)
                std::printf(",%s", format_value(d, fd, fields[k], i).c_str());
        }
        std::printf("\n");
    }
    return 0;
}
