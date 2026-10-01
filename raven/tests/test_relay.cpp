// Relais TCP et UDP, de bout en bout : un equipement A, un equipement B, et
// RAVEN entre les deux. Scenarios 01 (TCP) et 02 (UDP, CRC32) repris de
// SwitchSpy.
//
//   raven_relay_tests <switchlink.rvndesc> <sensors.rvndesc>
//
// Ce que ces tests doivent prouver, dans l'ordre d'importance :
//   1. RAVEN ne perd AUCUN message relaye, et ne les abime pas ;
//   2. il en garde une copie exacte dans le .rvn, avec le sens de chacune ;
//   3. un moteur lent ne retarde pas le transfert : il fait perdre des trames
//      d'observation, ce qui se compte, et rien d'autre.
#include <atomic>
#include <chrono>
#include <cstdio>
#include <cstring>
#include <string>
#include <thread>
#include <vector>

#include "engine.h"
#include "net/01_tcp_simple/shared.hpp"
#include "net/02_udp_relay/shared.hpp"
#include "raven/rvn.h"
#include "raven/sockets.h"
#include "raven/spsc.h"

using namespace raven;

static int g_failed = 0;
#define CHECK(c) do { if (!(c)) { std::printf("ECHEC %s:%d : %s\n", __FILE__, __LINE__, #c); ++g_failed; } } while (0)

// Un port libre pour UDP ne l'est pas forcement pour TCP, et Windows refuse
// par ailleurs les ports de ses plages reservees (WSAEACCES, 10013). On
// reserve donc avec le MEME protocole que celui qui s'en servira.
static uint16_t free_tcp_port() {
    net::TcpListener l;
    l.listen(net::Endpoint("127.0.0.1", 0));
    return l.local_port();
}

static uint16_t free_udp_port() {
    net::UdpSocket s;
    s.bind(net::Endpoint("127.0.0.1", 0));
    return s.local_port();
}

// CRC32 (IEEE 802.3), table calculee au premier appel.
static uint32_t crc32(const void* data, std::size_t size) {
    static uint32_t table[256];
    static bool ready = false;
    if (!ready) {
        for (uint32_t i = 0; i < 256; ++i) {
            uint32_t c = i;
            for (int k = 0; k < 8; ++k) c = (c & 1) ? 0xEDB88320u ^ (c >> 1) : c >> 1;
            table[i] = c;
        }
        ready = true;
    }
    const unsigned char* p = static_cast<const unsigned char*>(data);
    uint32_t c = 0xFFFFFFFFu;
    for (std::size_t i = 0; i < size; ++i) c = table[(c ^ p[i]) & 0xFF] ^ (c >> 8);
    return c ^ 0xFFFFFFFFu;
}

// RAVEN, comme raven.exe : la source alimente le moteur dans un fil dedie.
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
        if (!source) { std::printf("source refusee : %s\n", spec.c_str()); return false; }
        engine->command("rec_all 1");
        engine->command("path " + rvn);
        engine->command("arm");
        th = std::thread([this] {
            while (!stop) {
                const size_t n = source->poll([&](const Frame& f) { engine->on_frame(f); });
                engine->set_source(source->connected(), source->lost(), source->error());
                if (n == 0) std::this_thread::sleep_for(std::chrono::microseconds(200));
            }
        });
        return true;
    }
    void finish() {
        std::this_thread::sleep_for(std::chrono::milliseconds(300));   // vider les files
        stop = true;
        th.join();
        engine->command("stop");
    }
    ~Raven() { if (th.joinable()) { stop = true; th.join(); } }
};

// ------------------------------------------------------- scenario 01 : TCP
// A envoie des commandes, B acquitte. RAVEN relaie les deux sens et enregistre.
static void scenario_tcp(const char* desc) {
    std::printf("-- 01 relais TCP\n");
    const uint64_t kCount = 500;
    const uint16_t port_r = free_tcp_port();
    const std::string rvn = "relay_tcp.rvn";

    // --- B : le vrai destinataire. Verifie chaque commande et repond.
    // Il prend le port que le systeme veut bien lui donner et l'annonce :
    // deviner un port libre a sa place, c'est s'exposer a sa place.
    std::atomic<uint64_t> b_received{0}, b_bad{0};
    std::atomic<uint16_t> port_b{0};
    std::atomic<bool> b_ready{false}, b_failed{false};
    std::thread b([&] {
        net::TcpListener srv;
        if (!srv.listen(net::Endpoint("127.0.0.1", 0))) {
            std::printf("B : %s\n", srv.error().c_str());
            b_failed = true;
            return;
        }
        port_b = srv.local_port();
        b_ready = true;
        net::TcpSocket c = srv.accept(5000);
        if (!c.valid()) { std::printf("B : personne ne s'est connecte\n"); return; }
        for (uint64_t i = 0; i < kCount; ++i) {
            SwitchCommand cmd;
            if (!c.recv_all(&cmd, sizeof cmd, 5000)) break;
            // Integrite : la charge utile est deduite du numero de sequence.
            for (int k = 0; k < 16; ++k)
                if (cmd.payload[k] != uint8_t(cmd.sequence + k)) ++b_bad;
            if (cmd.port_id != uint16_t(cmd.sequence % 48)) ++b_bad;
            ++b_received;
            SwitchAck ack;
            std::memset(&ack, 0, sizeof ack);
            ack.sequence = cmd.sequence;
            ack.completed_ns = cmd.issued_ns + 1000;
            ack.result = 0;
            ack.port_state = 1;
            ack.throughput_kbps = uint32_t(cmd.sequence * 10);
            if (!c.send_all(&ack, sizeof ack, 5000)) break;
        }
    });
    for (int i = 0; i < 500 && !b_ready && !b_failed; ++i)
        std::this_thread::sleep_for(std::chrono::milliseconds(2));
    CHECK(b_ready);
    if (!b_ready) { b.join(); return; }       // inutile de s'acharner deux minutes

    // --- RAVEN au milieu.
    Raven r;
    char spec[256];
    std::snprintf(spec, sizeof spec, "tcp:127.0.0.1:%u|127.0.0.1:%u|SwitchCommand|SwitchAck",
                  unsigned(port_r), unsigned(port_b.load()));
    if (!r.start(desc, spec, rvn)) { ++g_failed; b.join(); return; }

    // --- A : le controleur. Envoie, puis verifie les acquittements.
    net::TcpSocket a;
    bool up = false;
    for (int i = 0; i < 500 && !up; ++i) {
        up = a.connect(net::Endpoint("127.0.0.1", port_r), 200);
        if (!up) std::this_thread::sleep_for(std::chrono::milliseconds(10));
    }
    CHECK(up);
    uint64_t acks = 0, ack_bad = 0;
    if (up) {
        for (uint64_t seq = 1; seq <= kCount; ++seq) {
            SwitchCommand cmd;
            std::memset(&cmd, 0, sizeof cmd);
            cmd.sequence = seq;
            cmd.issued_ns = seq * 1000000ull;
            cmd.port_id = uint16_t(seq % 48);
            cmd.action = uint8_t(seq % 4);
            cmd.priority = uint8_t(seq % 8);
            cmd.rate_limit_kbps = uint32_t(seq * 100);
            for (int k = 0; k < 16; ++k) cmd.payload[k] = uint8_t(seq + k);
            if (!a.send_all(&cmd, sizeof cmd, 5000)) { std::printf("A : envoi rompu\n"); break; }
            SwitchAck ack;
            if (!a.recv_all(&ack, sizeof ack, 5000)) { std::printf("A : acquittement manquant\n"); break; }
            if (ack.sequence != seq || ack.throughput_kbps != uint32_t(seq * 10)) ++ack_bad;
            ++acks;
        }
    }
    b.join();
    r.finish();

    // 1. Rien de perdu, rien d'abime, dans les deux sens.
    CHECK(b_received == kCount);
    CHECK(b_bad == 0);
    CHECK(acks == kCount);
    CHECK(ack_bad == 0);

    // 2. Le .rvn porte les deux sens, et le compte y est.
    std::string err;
    RvnReader rr;
    CHECK(rr.open(rvn, err));
    if (!err.empty()) std::printf("%s\n", err.c_str());
    uint64_t a2b = 0, b2a = 0, sans_sens = 0;
    uint64_t no, t;
    std::vector<const unsigned char*> fields;
    for (uint64_t n = 0; rr.read(n, no, t, fields); ++n) {
        switch (rr.last_direction()) {
            case Direction::AtoB: ++a2b; break;
            case Direction::BtoA: ++b2a; break;
            default: ++sans_sens; break;
        }
    }
    std::printf("   enregistres : %llu A>B, %llu B>A, %llu sans sens\n",
                (unsigned long long)a2b, (unsigned long long)b2a, (unsigned long long)sans_sens);
    CHECK(sans_sens == 0);
    CHECK(a2b > 0 && b2a > 0);
    CHECK(a2b + b2a == rr.count());
    // Les pertes annoncees expliquent exactement l'ecart avec ce qui a passe.
    CHECK(a2b + b2a + r.source->lost() == 2 * kCount);
    std::printf("   observation perdue : %llu\n", (unsigned long long)r.source->lost());
    std::remove(rvn.c_str());
}

// ------------------------------------------------------- scenario 02 : UDP
// Sans connexion : le CRC dit ce qui est abime, la sequence ce qui manque.
static void scenario_udp(const char* desc) {
    std::printf("-- 02 relais UDP\n");
    const uint64_t kCount = 2000;
    const uint16_t port_r = free_udp_port();
    const std::string rvn = "relay_udp.rvn";

    std::atomic<uint64_t> b_received{0}, b_crc_bad{0}, b_gaps{0};
    std::atomic<uint16_t> port_b{0};
    std::atomic<bool> b_ready{false}, b_stop{false}, b_failed{false};
    std::thread b([&] {
        net::UdpSocket s;
        if (!s.bind(net::Endpoint("127.0.0.1", 0))) {
            std::printf("B : %s\n", s.error().c_str());
            b_failed = true;
            return;
        }
        port_b = s.local_port();
        s.set_receive_buffer(4 << 20);
        b_ready = true;
        uint64_t last = 0;
        net::Endpoint from;
        while (!b_stop) {
            SensorReading rd;
            const long got = s.recv_from(&rd, sizeof rd, from, 50);
            if (got <= 0) continue;
            if (uint32_t(got) != sizeof rd) { ++b_crc_bad; continue; }
            if (crc32(&rd, sizeof rd - sizeof rd.crc32) != rd.crc32) ++b_crc_bad;
            if (last && rd.sequence > last + 1) b_gaps += rd.sequence - last - 1;
            last = rd.sequence;
            ++b_received;
            // Reponse : c'est elle qui exerce le sens B vers A.
            SensorSetpoint sp;
            std::memset(&sp, 0, sizeof sp);
            sp.sequence = rd.sequence;
            sp.sensor_id = rd.sensor_id;
            sp.period_us = 1000;
            sp.crc32 = crc32(&sp, sizeof sp - 2 * sizeof sp.crc32);
            s.send_to(&sp, sizeof sp, from);
        }
    });
    for (int i = 0; i < 500 && !b_ready && !b_failed; ++i)
        std::this_thread::sleep_for(std::chrono::milliseconds(2));
    CHECK(b_ready);
    if (!b_ready) { b_stop = true; b.join(); return; }

    Raven r;
    char spec[256];
    std::snprintf(spec, sizeof spec, "udp:127.0.0.1:%u|127.0.0.1:%u|SensorReading|SensorSetpoint",
                  unsigned(port_r), unsigned(port_b.load()));
    if (!r.start(desc, spec, rvn)) { ++g_failed; b_stop = true; b.join(); return; }
    std::this_thread::sleep_for(std::chrono::milliseconds(100));   // laisser lier le port

    // A : emet, et compte les consignes qui reviennent.
    net::UdpSocket a;
    CHECK(a.bind(net::Endpoint("127.0.0.1", 0)));
    a.set_receive_buffer(4 << 20);
    uint64_t sent = 0, setpoints = 0, sp_bad = 0;
    const net::Endpoint to("127.0.0.1", port_r);
    for (uint64_t seq = 1; seq <= kCount; ++seq) {
        SensorReading rd;
        std::memset(&rd, 0, sizeof rd);
        rd.sequence = seq;
        rd.sampled_ns = seq * 1000ull;
        rd.sensor_id = uint32_t(seq % 16);
        rd.value_e3 = int32_t(seq) * 7 - 3000;
        rd.unit = 1;
        rd.quality = uint8_t(seq % 101);
        rd.flags = 1;
        rd.crc32 = crc32(&rd, sizeof rd - sizeof rd.crc32);
        if (a.send_to(&rd, sizeof rd, to) == long(sizeof rd)) ++sent;
        if (seq % 100 == 0) std::this_thread::sleep_for(std::chrono::milliseconds(2));
        // Vider ce qui revient au fil de l'eau, sans bloquer l'emission.
        for (;;) {
            SensorSetpoint sp;
            net::Endpoint from;
            if (a.recv_from(&sp, sizeof sp, from, 0) != long(sizeof sp)) break;
            if (crc32(&sp, sizeof sp - 2 * sizeof sp.crc32) != sp.crc32) ++sp_bad;
            ++setpoints;
        }
    }
    // Laisser le reste des consignes arriver.
    for (int i = 0; i < 200; ++i) {
        SensorSetpoint sp;
        net::Endpoint from;
        if (a.recv_from(&sp, sizeof sp, from, 10) != long(sizeof sp)) continue;
        if (crc32(&sp, sizeof sp - 2 * sizeof sp.crc32) != sp.crc32) ++sp_bad;
        ++setpoints;
    }
    b_stop = true;
    b.join();
    r.finish();

    std::printf("   emis %llu, recus par B %llu, consignes revenues %llu\n",
                (unsigned long long)sent, (unsigned long long)b_received.load(),
                (unsigned long long)setpoints);
    CHECK(sent == kCount);
    // UDP en boucle locale ne perd rien en pratique ; s'il perdait, la
    // sequence le dirait, et c'est cela qu'on verifie plutot qu'une egalite.
    CHECK(b_received > kCount * 9 / 10);
    CHECK(b_crc_bad == 0);          // aucun message abime par le relais
    CHECK(b_gaps == 0);             // aucun trou dans la numerotation
    CHECK(setpoints > 0);
    CHECK(sp_bad == 0);

    std::string err;
    RvnReader rr;
    CHECK(rr.open(rvn, err));
    uint64_t a2b = 0, b2a = 0;
    uint64_t no, t;
    std::vector<const unsigned char*> fields;
    for (uint64_t n = 0; rr.read(n, no, t, fields); ++n) {
        if (rr.last_direction() == Direction::AtoB) ++a2b;
        else if (rr.last_direction() == Direction::BtoA) ++b2a;
    }
    std::printf("   enregistres : %llu A>B, %llu B>A\n",
                (unsigned long long)a2b, (unsigned long long)b2a);
    CHECK(a2b > 0 && b2a > 0);
    std::remove(rvn.c_str());
}

// --------------------------------------------------- file sans verrou seule
// La file est le cœur du montage : elle doit perdre plutot que bloquer, et ne
// jamais melanger deux trames.
static void queue_unit() {
    std::printf("-- file SPSC\n");
    FrameQueue q(4, 8);                       // arrondi a 4 emplacements
    CHECK(q.capacity() == 4);
    unsigned char out[8];
    Frame f;
    CHECK(!q.pop(f, out));                    // vide

    for (int i = 0; i < 4; ++i) {
        const uint64_t v = 0x1122334455667700ull + uint64_t(i);
        CHECK(q.push(uint64_t(i), 10 + uint64_t(i), i % 2, Direction::AtoB, &v, sizeof v));
    }
    // Pleine : la trame suivante est perdue et comptee, sans blocage.
    const uint64_t trop = 0;
    CHECK(!q.push(9, 9, 0, Direction::AtoB, &trop, sizeof trop));
    CHECK(q.dropped() == 1);
    CHECK(q.size() == 4);

    for (int i = 0; i < 4; ++i) {
        CHECK(q.pop(f, out));
        uint64_t v = 0;
        std::memcpy(&v, f.data, sizeof v);
        CHECK(f.no == uint64_t(i));                       // ordre conserve
        CHECK(v == 0x1122334455667700ull + uint64_t(i));  // contenu intact
        CHECK(f.dir == Direction::AtoB);
        CHECK(f.channel == i % 2);
    }
    CHECK(!q.pop(f, out));

    // Un message plus grand que la capacite d'un emplacement est refuse, pas
    // tronque : une trame a moitie ecrite serait pire qu'une trame absente.
    unsigned char gros[16] = {0};
    CHECK(!q.push(1, 1, 0, Direction::AtoB, gros, sizeof gros));
    CHECK(q.dropped() == 2);

    // Un producteur, un consommateur, en parallele : rien ne se perd ni ne se
    // melange quand la file ne deborde pas.
    FrameQueue big(4096, 8);
    const uint64_t kN = 200000;
    std::atomic<uint64_t> pushed{0};
    std::thread prod([&] {
        for (uint64_t i = 0; i < kN; ++i) {
            while (!big.push(i, i, 0, Direction::BtoA, &i, sizeof i))
                std::this_thread::yield();
            ++pushed;
        }
    });
    uint64_t got = 0, desordre = 0, abime = 0;
    unsigned char buf[8];
    Frame g;
    while (got < kN) {
        if (!big.pop(g, buf)) { std::this_thread::yield(); continue; }
        uint64_t v = 0;
        std::memcpy(&v, g.data, sizeof v);
        if (g.no != got) ++desordre;
        if (v != got) ++abime;
        ++got;
    }
    prod.join();
    CHECK(pushed == kN);
    CHECK(got == kN);
    CHECK(desordre == 0);
    CHECK(abime == 0);
    // dropped() n'est pas verifie ici : la boucle de reprise ci-dessus compte
    // un refus a chaque tour, alors qu'un refus ne devient une perte que si
    // l'appelant renonce, ce que fait le relais et pas ce test.
}

int main(int argc, char** argv) {
    if (argc < 3) {
        std::printf("usage : raven_relay_tests <switchlink.rvndesc> <sensors.rvndesc>\n");
        return 2;
    }
    // Sans tampon : un abort ne viderait pas stdout, et l'on perdrait
    // justement la trace de l'endroit ou l'on a echoue.
    std::setvbuf(stdout, nullptr, _IONBF, 0);
    net::init();
    queue_unit();
    scenario_tcp(argv[1]);
    scenario_udp(argv[2]);
    std::printf(g_failed ? "%d echec(s)\n" : "tout passe\n", g_failed);
    return g_failed ? 1 : 0;
}
