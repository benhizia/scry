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
#include <cmath>
#include <cstring>
#include <string>
#include <thread>
#include <vector>

#include "engine.h"
#include "hub.h"
#include "net/01_tcp_simple/shared.hpp"
#include "net/02_udp_relay/shared.hpp"
#include "net/06_complex_structs/shared.hpp"
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

// --------------------------------------------- scenario 06 : structs complexes
// Imbrication, tableaux de structures, tableaux de scalaires, enum a valeurs
// non contigues, chaine, drapeaux en entier masque.
//
// Ce que ce scenario prouve, et que les deux autres ne prouvent pas : le
// DESCRIPTEUR decrit la realite. Les octets recus sont relus par les offsets
// du .rvndesc, et compares aux valeurs emises. Si Scry se trompait d'un seul
// octet, aucun champ ne tomberait juste.

// Valeurs attendues, deduites du numero de sequence : le test n'a ainsi rien a
// memoriser entre l'emission et la relecture.
static LegPhase attendu_phase(int i) {
    const LegPhase table[4] = {LegPhase::Taxi, LegPhase::Climb, LegPhase::Cruise,
                               LegPhase::Hold};
    return table[i];
}
static int32_t attendu_altitude(uint64_t seq, int i) { return int32_t(1000 * (i + 1) + seq); }
static double attendu_gain(uint64_t seq, int j) { return 0.5 * (j + 1) + double(seq) * 0.001; }
static uint32_t attendu_flags(uint64_t seq) {
    return uint32_t(seq & 1) | uint32_t((seq >> 1) & 1) << 1 | uint32_t(seq % 97 == 0) << 2
           | uint32_t(seq % 256) << 8;
}

static void remplir(ComplexCommand& c, uint64_t seq) {
    std::memset(&c, 0, sizeof c);
    c.header.sequence = seq;
    c.header.emitted_ns = seq * 2500000ull;
    c.header.source_id = 0x1234;
    c.header.version = 3;
    std::snprintf(c.callsign, sizeof c.callsign, "AF%04u", unsigned(seq % 10000));
    for (int i = 0; i < 4; ++i) {
        c.legs[i].phase = attendu_phase(i);
        c.legs[i].altitude_ft = attendu_altitude(seq, i);
        c.legs[i].speed_kt_e2 = uint32_t(25000 + i * 100);
        c.legs[i].duration_ms = uint32_t(60000 + i);
    }
    for (int j = 0; j < 3; ++j) c.gains[j] = attendu_gain(seq, j);
    c.fuel_kg = 1200.5f + float(seq);
    c.flags = attendu_flags(seq);
}

// Relit un message avec le descripteur SEUL, sans connaitre les types C++, et
// compare a ce qui a ete emis. C'est le coeur du scenario.
static void verifier_par_le_descripteur(const Descriptor& d, const ChannelDesc& ch,
                                        const unsigned char* bytes, uint64_t seq,
                                        uint64_t& ecarts) {
    auto champ = [&](const char* chemin) -> const FieldDesc* {
        const FieldRef r = d.find(std::string(ch.name) + "." + chemin);
        return d.field(r);
    };
    auto entier = [&](const char* chemin, uint32_t index = 0) -> int64_t {
        const FieldDesc* f = champ(chemin);
        if (!f) { ++ecarts; return 0; }
        return read_integer(*f, bytes + f->offset, index);
    };
    auto reel = [&](const char* chemin, uint32_t index = 0) -> double {
        const FieldDesc* f = champ(chemin);
        if (!f) { ++ecarts; return 0.0; }
        return read_number(*f, bytes + f->offset, index);
    };

    if (entier("header.sequence") != int64_t(seq)) ++ecarts;
    if (entier("header.source_id") != 0x1234) ++ecarts;
    if (entier("header.version") != 3) ++ecarts;
    if (entier("flags") != int64_t(attendu_flags(seq))) ++ecarts;

    // Chaine : un tableau de caracteres, element par element.
    char lu[8] = {0};
    const FieldDesc* cs = champ("callsign");
    if (!cs || cs->count != 8) ++ecarts;
    else
        for (uint32_t i = 0; i < 8; ++i) lu[i] = char(read_integer(*cs, bytes + cs->offset, i));
    char veut[8];
    std::snprintf(veut, sizeof veut, "AF%04u", unsigned(seq % 10000));
    if (std::strcmp(lu, veut) != 0) ++ecarts;

    // Tableau de scalaires : le descripteur porte count, l'index suffit.
    for (uint32_t j = 0; j < 3; ++j)
        if (std::abs(reel("gains", j) - attendu_gain(seq, j)) > 1e-9) ++ecarts;
    if (std::abs(reel("fuel_kg") - double(1200.5f + float(seq))) > 1e-3) ++ecarts;

    // Tableau de STRUCTURES. Chaque element est un champ a part entiere,
    // 'legs[2].altitude_ft', a son propre offset : le relecteur n'a aucune
    // arithmetique a faire, il demande le chemin qu'il veut.
    for (int i = 0; i < 4; ++i) {
        char chemin[64];
        std::snprintf(chemin, sizeof chemin, "legs[%d].phase", i);
        if (entier(chemin) != int64_t(attendu_phase(i))) ++ecarts;
        std::snprintf(chemin, sizeof chemin, "legs[%d].altitude_ft", i);
        if (entier(chemin) != attendu_altitude(seq, i)) ++ecarts;
        std::snprintf(chemin, sizeof chemin, "legs[%d].speed_kt_e2", i);
        if (entier(chemin) != int64_t(25000 + i * 100)) ++ecarts;
    }
    // Le dernier element doit exister, et pas un cinquieme.
    if (!champ("legs[3].phase")) ++ecarts;
    if (champ("legs[4].phase")) ++ecarts;

    // L'enum se rend en texte, ce qui est l'interet d'avoir le descripteur.
    const FieldDesc* phase = champ("legs[0].phase");
    if (!phase) { ++ecarts; return; }
    const EnumDesc* e = d.enum_of(*phase);
    if (!e || !e->name_of(int64_t(LegPhase::Cruise))
        || std::string(e->name_of(int64_t(LegPhase::Cruise))) != "Cruise") ++ecarts;
}

static void scenario_complex(const char* desc) {
    std::printf("-- 06 structs complexes\n");
    const uint64_t kCount = 300;
    const uint16_t port_r = free_tcp_port();
    const std::string rvn = "relay_complex.rvn";

    std::atomic<uint64_t> b_received{0}, b_bad{0};
    std::atomic<uint16_t> port_b{0};
    std::atomic<bool> b_ready{false}, b_failed{false};
    std::thread b([&] {
        net::TcpListener srv;
        if (!srv.listen(net::Endpoint("127.0.0.1", 0))) { b_failed = true; return; }
        port_b = srv.local_port();
        b_ready = true;
        net::TcpSocket c = srv.accept(5000);
        if (!c.valid()) return;
        for (uint64_t i = 0; i < kCount; ++i) {
            ComplexCommand got;
            if (!c.recv_all(&got, sizeof got, 5000)) break;
            ComplexCommand veut;
            remplir(veut, got.header.sequence);
            // Octet pour octet : le relais n'a pas le droit de toucher au
            // message, pas meme a son bourrage.
            if (std::memcmp(&got, &veut, sizeof got) != 0) ++b_bad;
            ++b_received;
            ComplexReply rep;
            std::memset(&rep, 0, sizeof rep);
            rep.header = got.header;
            rep.active_leg = uint8_t(got.header.sequence % 4);
            rep.phase = got.legs[rep.active_leg].phase;
            rep.altitude_ft = got.legs[rep.active_leg].altitude_ft;
            rep.flags = got.flags;
            if (!c.send_all(&rep, sizeof rep, 5000)) break;
        }
    });
    for (int i = 0; i < 500 && !b_ready && !b_failed; ++i)
        std::this_thread::sleep_for(std::chrono::milliseconds(2));
    CHECK(b_ready);
    if (!b_ready) { b.join(); return; }

    Raven r;
    char spec[256];
    std::snprintf(spec, sizeof spec, "tcp:127.0.0.1:%u|127.0.0.1:%u|ComplexCommand|ComplexReply",
                  unsigned(port_r), unsigned(port_b.load()));
    if (!r.start(desc, spec, rvn)) { ++g_failed; b.join(); return; }

    // Ce que Scry promet avant tout : la taille annoncee est celle du
    // compilateur. Si elle differait, le relais decouperait le flux au mauvais
    // endroit et tout le reste serait faux.
    const ChannelDesc* ch_cmd = nullptr;
    const ChannelDesc* ch_rep = nullptr;
    for (const ChannelDesc& c : r.d.channels()) {
        if (c.name == "ComplexCommand") ch_cmd = &c;
        if (c.name == "ComplexReply") ch_rep = &c;
    }
    CHECK(ch_cmd != nullptr && ch_rep != nullptr);
    if (ch_cmd) CHECK(ch_cmd->size == sizeof(ComplexCommand));
    if (ch_rep) CHECK(ch_rep->size == sizeof(ComplexReply));

    net::TcpSocket a;
    bool up = false;
    for (int i = 0; i < 500 && !up; ++i) {
        up = a.connect(net::Endpoint("127.0.0.1", port_r), 200);
        if (!up) std::this_thread::sleep_for(std::chrono::milliseconds(10));
    }
    CHECK(up);
    uint64_t replies = 0, rep_bad = 0, ecarts = 0;
    if (up) {
        for (uint64_t seq = 1; seq <= kCount; ++seq) {
            ComplexCommand cmd;
            remplir(cmd, seq);
            if (!a.send_all(&cmd, sizeof cmd, 5000)) break;
            ComplexReply rep;
            if (!a.recv_all(&rep, sizeof rep, 5000)) break;
            if (rep.header.sequence != seq) ++rep_bad;
            if (rep.altitude_ft != attendu_altitude(seq, int(seq % 4))) ++rep_bad;
            if (rep.flags != attendu_flags(seq)) ++rep_bad;
            ++replies;
            // Decodage par le descripteur seul, sur les octets du message.
            if (ch_cmd)
                verifier_par_le_descripteur(r.d, *ch_cmd,
                                            reinterpret_cast<const unsigned char*>(&cmd),
                                            seq, ecarts);
        }
    }
    b.join();
    r.finish();

    std::printf("   relayes %llu, acquittes %llu, ecarts de decodage %llu\n",
                (unsigned long long)b_received.load(), (unsigned long long)replies,
                (unsigned long long)ecarts);
    CHECK(b_received == kCount);
    CHECK(b_bad == 0);               // aucun octet modifie par le relais
    CHECK(replies == kCount);
    CHECK(rep_bad == 0);
    CHECK(ecarts == 0);              // le descripteur decrit la realite

    // Le .rvn : ce qu'il porte doit se relire par le descripteur aussi.
    std::string err;
    RvnReader rr;
    CHECK(rr.open(rvn, err));
    if (!err.empty()) std::printf("%s\n", err.c_str());
    uint64_t a2b = 0, b2a = 0, rvn_ecarts = 0;
    uint64_t no, t;
    std::vector<const unsigned char*> fields;
    // Position, dans la selection enregistree, des champs que l'on veut
    // relire. legs[3] est la : le .rvn enregistre bien TOUS les elements d'un
    // tableau de structures, et non le premier seulement.
    auto place = [&](const char* chemin) -> int {
        const FieldRef r = rr.descriptor().find(std::string("ComplexCommand.") + chemin);
        for (std::size_t k = 0; k < rr.selection().size(); ++k)
            if (rr.selection()[k] == r) return int(k);
        return -1;
    };
    const int k_seq = place("header.sequence");
    const int k_alt3 = place("legs[3].altitude_ft");
    CHECK(k_seq >= 0);
    CHECK(k_alt3 >= 0);
    for (uint64_t n = 0; rr.read(n, no, t, fields); ++n) {
        if (rr.last_direction() == Direction::AtoB) ++a2b;
        else if (rr.last_direction() == Direction::BtoA) ++b2a;
        if (k_seq < 0 || k_alt3 < 0) continue;
        const FieldRef r_seq = rr.descriptor().find("ComplexCommand.header.sequence");
        const FieldRef r_alt = rr.descriptor().find("ComplexCommand.legs[3].altitude_ft");
        const int64_t s = read_integer(*rr.descriptor().field(r_seq),
                                       fields[std::size_t(k_seq)]);
        // Chaque enregistrement porte l'etat de TOUS les champs choisis : une
        // sequence de commande hors bornes serait une corruption.
        if (s < 1 || s > int64_t(kCount)) { ++rvn_ecarts; continue; }
        const int64_t alt = read_integer(*rr.descriptor().field(r_alt),
                                         fields[std::size_t(k_alt3)]);
        if (alt != attendu_altitude(uint64_t(s), 3)) ++rvn_ecarts;
    }
    std::printf("   enregistres : %llu A>B, %llu B>A, ecarts %llu\n",
                (unsigned long long)a2b, (unsigned long long)b2a,
                (unsigned long long)rvn_ecarts);
    CHECK(a2b > 0 && b2a > 0);
    CHECK(rvn_ecarts == 0);
    std::remove(rvn.c_str());
}

// ------------------------------------------- plusieurs liaisons a la fois
// Deux liaisons dans un seul raven : chacune son descripteur, sa source, son
// moteur et son enregistrement. Le visualiseur passe de l'une a l'autre.
static void scenario_multi(const char* desc_switch, const char* desc_route) {
    std::printf("-- plusieurs liaisons\n");

    // Deux equipements B. Chacun recoit un message d'une taille et repond d'une
    // AUTRE : c'est le cas normal, un acquittement n'a pas la forme d'une
    // commande, et le relais attend bien la taille du canal de chaque sens.
    // Les deux types de reponse portent la sequence dans leurs huit premiers
    // octets, ce qui suffit a l'appelant pour s'y retrouver.
    struct Echo {
        std::atomic<uint16_t> port{0};
        std::atomic<bool> ready{false}, stop{false};
        std::atomic<uint64_t> seen{0};
        std::thread th;
        void start(std::size_t in_size, std::size_t out_size) {
            th = std::thread([this, in_size, out_size] {
                net::TcpListener srv;
                if (!srv.listen(net::Endpoint("127.0.0.1", 0))) return;
                port = srv.local_port();
                ready = true;
                net::TcpSocket c = srv.accept(5000);
                std::vector<unsigned char> in(in_size), out(out_size, 0);
                while (c.valid() && !stop) {
                    if (!c.recv_all(in.data(), in.size(), 200)) continue;
                    ++seen;
                    std::memcpy(out.data(), in.data(), 8);     // la sequence
                    if (!c.send_all(out.data(), out.size(), 1000)) break;
                }
            });
        }
        void finish() { stop = true; if (th.joinable()) th.join(); }
    };
    Echo b1, b2;
    b1.start(sizeof(SwitchCommand), sizeof(SwitchAck));
    b2.start(sizeof(ComplexCommand), sizeof(ComplexReply));
    for (int i = 0; i < 500 && !(b1.ready && b2.ready); ++i)
        std::this_thread::sleep_for(std::chrono::milliseconds(2));
    CHECK(b1.ready && b2.ready);
    if (!(b1.ready && b2.ready)) { b1.finish(); b2.finish(); return; }

    const uint16_t p1 = free_tcp_port(), p2 = free_tcp_port();
    std::vector<LinkConfig> cfgs(2);
    char spec[256];
    cfgs[0].name = "commandes";
    cfgs[0].desc_path = desc_switch;
    std::snprintf(spec, sizeof spec, "tcp:127.0.0.1:%u|127.0.0.1:%u|SwitchCommand|SwitchAck",
                  unsigned(p1), unsigned(b1.port.load()));
    cfgs[0].source = spec;
    cfgs[0].record_path = "multi_cmd.rvn";
    cfgs[1].name = "route";
    cfgs[1].desc_path = desc_route;
    std::snprintf(spec, sizeof spec,
                  "tcp:127.0.0.1:%u|127.0.0.1:%u|ComplexCommand|ComplexReply",
                  unsigned(p2), unsigned(b2.port.load()));
    cfgs[1].source = spec;
    cfgs[1].record_path = "multi_route.rvn";

    Hub hub;
    std::string err;
    CHECK(hub.start(cfgs, err));
    if (!err.empty()) std::printf("%s\n", err.c_str());
    CHECK(hub.size() == 2);

    // 'links' nomme les deux, et marque celle dont on parle.
    const std::string liste = hub.command("links");
    CHECK(liste.find("link 0 commandes") != std::string::npos);
    CHECK(liste.find("link 1 route") != std::string::npos);
    CHECK(liste.find(" *") != std::string::npos);

    // Par defaut la premiere : le dialogue d'un visualiseur qui ignore 'use'
    // est donc exactement celui d'avant.
    CHECK(hub.command("hello").find("ComplexCommand") == std::string::npos);
    CHECK(hub.command("hello").find("SwitchCommand") != std::string::npos);

    // 'use' rend le descripteur de la nouvelle liaison : sans lui, le
    // visualiseur ne saurait rien lire.
    const std::string bascule = hub.command("use route");
    CHECK(bascule.find("ComplexCommand") != std::string::npos);
    CHECK(hub.command("hello").find("ComplexCommand") != std::string::npos);
    // Par indice aussi.
    CHECK(hub.command("use 0").find("SwitchCommand") != std::string::npos);
    // Et un nom inconnu est refuse en nommant ce qui existe.
    const std::string refus = hub.command("use inexistante");
    CHECK(refus.find("err liaison inconnue") != std::string::npos);
    CHECK(refus.find("link 1 route") != std::string::npos);

    // Les deux liaisons enregistrent, chacune pour son compte.
    hub.command("use commandes");
    hub.command("rec_all 1");
    hub.command("arm");
    hub.command("use route");
    hub.command("rec_all 1");
    hub.command("arm");

    // Du trafic sur les deux, en parallele.
    net::TcpSocket a1, a2;
    bool up1 = false, up2 = false;
    for (int i = 0; i < 500 && !(up1 && up2); ++i) {
        if (!up1) up1 = a1.connect(net::Endpoint("127.0.0.1", p1), 200);
        if (!up2) up2 = a2.connect(net::Endpoint("127.0.0.1", p2), 200);
        if (!(up1 && up2)) std::this_thread::sleep_for(std::chrono::milliseconds(10));
    }
    CHECK(up1 && up2);
    const uint64_t kN = 50;
    uint64_t echos1 = 0, echos2 = 0;
    for (uint64_t seq = 1; seq <= kN && up1 && up2; ++seq) {
        SwitchCommand c1;
        std::memset(&c1, 0, sizeof c1);
        c1.sequence = seq;
        c1.port_id = uint16_t(seq % 48);
        ComplexCommand c2;
        remplir(c2, seq);
        if (!a1.send_all(&c1, sizeof c1, 2000)) break;
        if (!a2.send_all(&c2, sizeof c2, 2000)) break;
        SwitchAck r1;
        ComplexReply r2;
        if (a1.recv_all(&r1, sizeof r1, 2000) && r1.sequence == seq) ++echos1;
        if (a2.recv_all(&r2, sizeof r2, 2000) && r2.header.sequence == seq) ++echos2;
    }
    std::this_thread::sleep_for(std::chrono::milliseconds(300));
    hub.stop_all_recordings();
    hub.stop();
    b1.finish();
    b2.finish();

    std::printf("   echos %llu et %llu, vus par B %llu et %llu\n",
                (unsigned long long)echos1, (unsigned long long)echos2,
                (unsigned long long)b1.seen.load(), (unsigned long long)b2.seen.load());
    CHECK(echos1 == kN);
    CHECK(echos2 == kN);

    // Chaque liaison a son propre .rvn, avec son propre descripteur.
    for (const char* f : {"multi_cmd.rvn", "multi_route.rvn"}) {
        RvnReader rr;
        std::string e;
        CHECK(rr.open(f, e));
        if (!e.empty()) std::printf("%s : %s\n", f, e.c_str());
        CHECK(rr.count() > 0);
        std::remove(f);
    }
}

int main(int argc, char** argv) {
    if (argc < 4) {
        std::printf("usage : raven_relay_tests <switchlink.rvndesc> <sensors.rvndesc>"
                    " <route.rvndesc>\n");
        return 2;
    }
    // Sans tampon : un abort ne viderait pas stdout, et l'on perdrait
    // justement la trace de l'endroit ou l'on a echoue.
    std::setvbuf(stdout, nullptr, _IONBF, 0);
    net::init();
    queue_unit();
    scenario_tcp(argv[1]);
    scenario_udp(argv[2]);
    scenario_complex(argv[3]);
    scenario_multi(argv[1], argv[3]);
    std::printf(g_failed ? "%d echec(s)\n" : "tout passe\n", g_failed);
    return g_failed ? 1 : 0;
}
