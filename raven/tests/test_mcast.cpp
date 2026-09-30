// Ecoute passive multicast, de bout en bout : un emetteur, un vrai
// consommateur, et RAVEN (plugin "mcast" + moteur + enregistrement) a cote.
// Scenarios 03 (telemetrie) et 04 (haut debit) repris de SwitchSpy.
//
//   raven_mcast_tests <telemetry.rvndesc> <market.rvndesc>
#include <atomic>
#include <chrono>
#include <cstdio>
#include <cstring>
#include <string>
#include <thread>
#include <vector>

#include "engine.h"
#include "net/03_multicast/shared.hpp"
#include "net/04_high_throughput/shared.hpp"
#include "raven/rvn.h"
#include "raven/sockets.h"

using namespace raven;

static int g_failed = 0;
#define CHECK(c) do { if (!(c)) { std::printf("ECHEC %s:%d : %s\n", __FILE__, __LINE__, #c); ++g_failed; } } while (0)

static uint16_t free_port() {
    net::UdpSocket s;
    s.bind(net::Endpoint("127.0.0.1", 0));
    return s.local_port();
}

// RAVEN : la source alimente le moteur dans son propre fil, comme raven.exe.
struct Raven {
    Descriptor d;
    std::unique_ptr<Engine> engine;
    std::unique_ptr<ISource> source;
    std::atomic<bool> stop{false};
    std::thread th;

    bool start(const std::string& desc, const std::string& spec, const std::string& rvn) {
        std::string err;
        if (!d.load(desc, err)) { std::printf("%s\n", err.c_str()); return false; }
        engine.reset(new Engine(d));
        source = make_source(spec, d);
        if (!source) return false;
        engine->command("rec_all 1");
        engine->command("path " + rvn);
        engine->command("arm");
        th = std::thread([this] {
            while (!stop) {
                source->poll([&](const Frame& f) { engine->on_frame(f); });
                engine->set_source(source->connected(), source->lost(), source->error());
            }
        });
        // Attendre l'abonnement avant d'emettre.
        for (int i = 0; i < 200 && !source->connected(); ++i)
            std::this_thread::sleep_for(std::chrono::milliseconds(5));
        return source->connected();
    }
    void finish() {
        std::this_thread::sleep_for(std::chrono::milliseconds(200));   // vider le tampon
        stop = true;
        th.join();
        engine->command("stop");
    }
};

// Emet 'count' messages, en sautant les numeros de 'skip_from' a 'skip_to'.
template <class Msg, class Fill>
static uint64_t emit(const net::Endpoint& group, uint64_t count, int burst, Fill fill,
                     uint64_t skip_from = 0, uint64_t skip_to = 0) {
    net::MulticastSocket tx;
    if (!tx.open_sender(group, "127.0.0.1", 1, true)) { std::printf("%s\n", tx.error().c_str()); return 0; }
    uint64_t sent = 0;
    for (uint64_t seq = 1; seq <= count; ++seq) {
        if (seq >= skip_from && seq <= skip_to) continue;
        Msg m;
        std::memset(&m, 0, sizeof m);
        fill(m, seq);
        if (tx.send(&m, sizeof m) == long(sizeof m)) ++sent;
        if (seq % burst == 0) std::this_thread::sleep_for(std::chrono::microseconds(500));
    }
    return sent;
}

static void scenario_03(const std::string& desc) {
    const net::Endpoint group("239.255.3.3", free_port());
    const std::string rvn = "raven_test_mcast03.rvn";
    // Le vrai consommateur, abonne au meme groupe et au meme port.
    net::MulticastSocket consumer;
    if (!consumer.join(group, "127.0.0.1")) {
        std::printf("multicast indisponible, scenario 03 saute : %s\n", consumer.error().c_str());
        return;
    }
    consumer.set_receive_buffer(8 << 20);
    Raven r;
    CHECK(r.start(desc, "mcast:" + group.str() + "@127.0.0.1#TelemetryBroadcast?seq=sequence", rvn));

    // 2000 messages dont 10 volontairement absents (100 a 109), un datagramme
    // parasite de mauvaise taille.
    const uint64_t sent = emit<TelemetryBroadcast>(group, 2010, 50, [](TelemetryBroadcast& m, uint64_t s) {
        m.source_id = 7;
        m.sequence = s;
        m.altitude_m = int16_t(s % 1000);
        m.status_flags = s == 1500 ? 4 : 1;
    }, 100, 109);
    {
        net::MulticastSocket tx;
        tx.open_sender(group, "127.0.0.1", 1, true);
        const char junk[5] = "abcd";
        tx.send(junk, sizeof junk);
    }
    uint64_t consumed = 0;
    std::vector<unsigned char> buf(2048);
    net::Endpoint from;
    while (consumer.recv_from(buf.data(), buf.size(), from, 300) > 0) ++consumed;
    r.finish();

    CHECK(sent == 2000);
    CHECK(consumed == 2001);                       // le consommateur recoit tout, parasite compris
    CHECK(r.source->lost() == 10);                 // le trou 100..109, et rien d'autre
    CHECK(r.engine->frames() == 2000);             // le parasite est ecarte par la source
    CHECK(r.source->error().find("ignores") != std::string::npos);

    RvnReader rd;
    std::string err;
    CHECK(rd.open(rvn, err));
    CHECK(rd.version() == 2 && rd.count() == 2000);
    const FieldRef seq = rd.descriptor().find("TelemetryBroadcast.sequence");
    size_t k = 0;
    while (k < rd.selection().size() && !(rd.selection()[k] == seq)) ++k;
    uint64_t no, t, prev = 0, gaps = 0;
    std::vector<const unsigned char*> fields;
    for (uint64_t n = 0; rd.read(n, no, t, fields); ++n) {
        CHECK(rd.last_channel() == 0);
        const uint64_t s = uint64_t(read_integer(*rd.descriptor().field(seq), fields[k]));
        if (prev && s != prev + 1) gaps += s - prev - 1;
        prev = s;
    }
    CHECK(gaps == 10 && prev == 2010);
    std::printf("scenario 03 : %llu messages, %llu perdus annonces, consommateur servi : %llu\n",
                (unsigned long long)r.engine->frames(), (unsigned long long)r.source->lost(),
                (unsigned long long)consumed);
    std::remove(rvn.c_str());
}

static void scenario_04(const std::string& desc) {
    const net::Endpoint group("239.255.4.4", free_port());
    const std::string rvn = "raven_test_mcast04.rvn";
    Raven r;
    if (!r.start(desc, "mcast:" + group.str() + "@127.0.0.1#MarketTick?seq=sequence", rvn)) {
        std::printf("multicast indisponible, scenario 04 saute\n");
        return;
    }
    const uint64_t n = 50000;
    const auto t0 = std::chrono::steady_clock::now();
    const uint64_t sent = emit<MarketTick>(group, n, 500, [](MarketTick& m, uint64_t s) {
        m.symbol_id = 42;
        m.sequence = s;
        m.bid_price_e4 = 1000000 + s;
    });
    const double secs = std::chrono::duration<double>(std::chrono::steady_clock::now() - t0).count();
    r.finish();

    // A haut debit, des pertes sont possibles ; ce qui est exige, c'est qu'aucune
    // ne soit silencieuse : recu + annonce perdu = emis.
    CHECK(sent == n);
    CHECK(r.engine->frames() + r.source->lost() == n);
    RvnReader rd;
    std::string err;
    CHECK(rd.open(rvn, err) && rd.count() == r.engine->frames());
    std::printf("scenario 04 : %llu messages en %.2f s (%.0f msg/s), %llu recus, %llu perdus annonces\n",
                (unsigned long long)n, secs, n / secs, (unsigned long long)r.engine->frames(),
                (unsigned long long)r.source->lost());
    std::remove(rvn.c_str());
}

int main(int argc, char** argv) {
    if (argc < 3) { std::printf("usage : raven_mcast_tests <telemetry.rvndesc> <market.rvndesc>\n"); return 2; }
    net::init();
    scenario_03(argv[1]);
    scenario_04(argv[2]);
    std::printf(g_failed ? "%d echec(s)\n" : "tests multicast : tout passe\n", g_failed);
    return g_failed ? 1 : 0;
}
