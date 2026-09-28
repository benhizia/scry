// Tests du coeur et du moteur, sans simulateur ni reseau : descripteur,
// anneau en memoire partagee, declencheur, enregistrement et relecture.
#include <chrono>
#include <cstdio>
#include <cstring>
#include <string>
#include <vector>

#include "engine.h"
#include "raven/net.h"
#include "raven/producer.h"
#include "raven/rvn.h"

using namespace raven;

static int g_failed = 0;
#define CHECK(c) do { if (!(c)) { std::printf("ECHEC %s:%d : %s\n", __FILE__, __LINE__, #c); ++g_failed; } } while (0)

// Descripteur minimal ecrit a la main : un canal de 16 octets.
static const char* kDesc =
    "rvndesc 1\n"
    "schema 0x00000000000000AB\n"
    "frame_size 16\n"
    "enum 0 3 demo::SimState\n"
    "item 0 Stopped\nitem 1 Running\nitem 2 Frozen\n"
    "channel 0 0 16 5 g_sim\n"
    "field 0 -1 enum 0 4 1 0 - state\n"
    "field 1 -1 struct 4 12 1 -1 - pos\n"
    "field 2 1 float 4 4 1 -1 ft pos.alt\n"
    "field 3 1 bool 8 1 1 -1 - pos.gear\n"
    "field 4 1 int 10 2 3 -1 - pos.v\n"
    "end\n";

struct Sim { int32_t state; float alt; bool gear; char pad; int16_t v[3]; };
static_assert(sizeof(Sim) == 16, "Sim");

static Descriptor load() {
    Descriptor d;
    std::string err;
    CHECK(d.parse(kDesc, err));
    return d;
}

static void test_descriptor() {
    Descriptor d = load();
    CHECK(d.schema() == 0xAB);
    CHECK(d.channels().size() == 1);
    const ChannelDesc& c = d.channels()[0];
    CHECK(c.roots.size() == 2 && c.fields[1].children.size() == 3);
    CHECK(d.find("g_sim.pos.alt") == (FieldRef{0, 2}));
    CHECK(d.field(FieldRef{0, 2})->unit == "ft");
    CHECK(d.leaves().size() == 4);

    Sim s = {1, 1234.5f, true, 0, {-1, 2, 3}};
    const auto* p = reinterpret_cast<const unsigned char*>(&s);
    CHECK(format_value(d, c.fields[0], p + 0) == "Running");
    CHECK(format_value(d, c.fields[2], p + 4) == "1234.5");
    CHECK(format_value(d, c.fields[3], p + 8) == "true");
    CHECK(format_value(d, c.fields[4], p + 10, 0) == "-1");
    CHECK(format_value(d, c.fields[4], p + 10, 2) == "3");

    std::string err;
    Descriptor bad;
    CHECK(!bad.parse("rvndesc 1\nframe_size 4\nchannel 0 0 4 1 x\nfield 0 -1 int 2 4 1 -1 - a\nend\n", err));
    CHECK(err.find("hors du canal") != std::string::npos);
    CHECK(!bad.parse("rvndesc 1\nframe_size 4\n", err));   // 'end' absent
}

// Anneau : toutes les trames arrivent, un retard trop long est compte en pertes.
static void test_ring() {
    Descriptor d = load();
    const std::string name = "raven_test_" + std::to_string(now_ns() % 100000);
    Producer prod;
    CHECK(prod.create(name, d.schema(), d.frame_size(), 8));
    auto src = make_source("shm:" + name, d);
    std::vector<uint64_t> seen;
    auto on = [&](const Frame& f) {
        Sim s;
        std::memcpy(&s, f.data, sizeof s);
        CHECK(s.v[0] == int16_t(f.no));
        seen.push_back(f.no);
    };
    auto publish = [&](int n) {
        for (int i = 0; i < n; ++i) {
            unsigned char* p = prod.begin_frame();
            Sim s = {1, 0, false, 0, {int16_t(prod.published() + 1), 0, 0}};
            std::memcpy(p, &s, sizeof s);
            prod.end_frame();
        }
    };
    publish(1);
    CHECK(src->poll(on) == 1);                       // s'accroche au present
    seen.clear();
    CHECK(src->connected());
    publish(5);
    CHECK(src->poll(on) == 5);
    CHECK(seen.size() == 5 && seen.front() == 2 && seen.back() == 6);
    CHECK(src->lost() == 0);
    publish(20);                                     // 20 trames pour 8 emplacements
    src->poll(on);
    CHECK(src->lost() == 12);
    CHECK(seen.back() == 26);

    auto wrong = make_source("shm:" + name, Descriptor());
    wrong->poll(on);
    CHECK(!wrong->connected() && !wrong->error().empty());
}

// Moteur : arme, attend le declencheur, enregistre les champs choisis, relit.
static void test_engine_record() {
    Descriptor d = load();
    Engine e(d);
    const std::string path = "raven_test_record.rvn";
    CHECK(e.command("arm").compare(0, 3, "err") == 0);          // rien a enregistrer
    CHECK(e.command("rec 0:2 1").compare(0, 2, "ok") == 0);
    CHECK(e.command("rec 0:4 1").compare(0, 2, "ok") == 0);
    CHECK(e.command("rec 0:1 1").compare(0, 3, "err") == 0);    // pas une feuille
    CHECK(e.command("trg 0:0 == 1").compare(0, 2, "ok") == 0);  // state == Running
    CHECK(e.command("sen 0:3 1").compare(0, 2, "ok") == 0);
    CHECK(e.command("path " + path).compare(0, 2, "ok") == 0);
    CHECK(e.command("arm") == "ok\n");
    CHECK(e.state() == RecState::Armed);

    for (uint64_t n = 1; n <= 10; ++n) {
        Sim s = {n >= 4 ? 1 : 0, float(n * 100), n == 6, 0, {int16_t(n), 0, 0}};
        Frame f;
        f.no = n;
        f.t_ns = n * 20000000ull;
        f.data = reinterpret_cast<const unsigned char*>(&s);
        f.size = sizeof s;
        e.on_frame(f);
        if (n == 3) CHECK(e.state() == RecState::Armed);
        if (n == 4) CHECK(e.state() == RecState::Recording);
    }
    const std::string up = e.updates();
    CHECK(up.find("st recording") == 0);
    CHECK(up.find("s 0:3 6 0 1 1") != std::string::npos);      // montee sur une trame
    CHECK(up.find("s 0:3 7 1 0 2") != std::string::npos);      // et retombee
    CHECK(e.command("stop") == "ok\n");
    CHECK(e.state() == RecState::Idle);

    RvnReader r;
    std::string err;
    CHECK(r.open(path, err));
    CHECK(r.count() == 7);                                      // trames 4 a 10
    CHECK(r.trigger() == "g_sim.state == Running");
    CHECK(r.selection().size() == 2);
    uint64_t no = 0, t = 0;
    std::vector<const unsigned char*> fields;
    CHECK(r.read(0, no, t, fields) && no == 4 && t == 80000000ull);
    float alt;
    std::memcpy(&alt, fields[0], 4);
    CHECK(alt == 400.0f);
    CHECK(r.read(6, no, t, fields) && no == 10);
    CHECK(!r.read(7, no, t, fields));
    std::remove(path.c_str());
}

// Un visualiseur qui ne lit jamais ne doit pas figer raven. La publication
// remplit une file plafonnee, abandonne des lots et rend la main tout de
// suite ; sans cela, le ::send bloquant arretait le moteur, commandes
// comprises, et un enregistrement ne pouvait plus etre arrete.
static void test_publication_non_bloquante() {
    CHECK(net_init());
    Listener listener;
    CHECK(listener.listen(0));
    const int port = listener.port();
    CHECK(port > 0);

    LineSocket viewer;                       // le visualiseur : il ne lit rien
    CHECK(viewer.connect("127.0.0.1", port));
    LineSocket client = listener.accept(2000);
    CHECK(client.valid());

    const std::string lot(64 * 1024, 'x');
    bool rendu = true;
    const auto debut = std::chrono::steady_clock::now();
    for (int i = 0; i < 200; ++i) rendu = client.queue(lot + "\n", true) && rendu;
    const auto ms = std::chrono::duration_cast<std::chrono::milliseconds>(
        std::chrono::steady_clock::now() - debut).count();

    CHECK(rendu);                            // jamais coupe
    CHECK(client.valid());
    CHECK(ms < 2000);                        // 12 Mio proposes sans attendre
    CHECK(client.dropped() > 0);             // des lots ont ete abandonnes
    CHECK(client.pending() <= LineSocket::kMaxOutbox);

    // Une reponse a une commande, elle, n'est jamais abandonnee.
    const std::size_t avant = client.dropped();
    CHECK(client.queue("ok\n"));
    CHECK(client.dropped() == avant);
}

int main() {
    test_descriptor();
    test_ring();
    test_engine_record();
    test_publication_non_bloquante();
    std::printf(g_failed ? "%d echec(s)\n" : "tous les tests passent\n", g_failed);
    return g_failed ? 1 : 0;
}
