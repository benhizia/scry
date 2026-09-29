// Tests de raven::net sur la boucle locale : TCP, UDP et multicast.
// Le multicast est saute (et signale) si le poste n'a pas de route multicast.
#include <cstdio>
#include <cstring>
#include <string>
#include <thread>
#include <vector>

#include "raven/sockets.h"

using namespace raven::net;

static int g_failed = 0;
#define CHECK(c) do { if (!(c)) { std::printf("ECHEC %s:%d : %s\n", __FILE__, __LINE__, #c); ++g_failed; } } while (0)

static void test_endpoint() {
    Endpoint e;
    CHECK(Endpoint::parse("192.168.1.10:8001", e) && e.host == "192.168.1.10" && e.port == 8001);
    CHECK(Endpoint::parse(":5000", e) && e.host == "0.0.0.0" && e.port == 5000);
    CHECK(Endpoint::parse("5000", e) && e.port == 5000);
    CHECK(!Endpoint::parse("hote:abc", e));
    CHECK(!Endpoint::parse("hote:70000", e));
    CHECK(Endpoint("239.1.1.1", 5000).str() == "239.1.1.1:5000");
}

static void test_tcp() {
    TcpListener l;
    CHECK(l.listen(Endpoint("127.0.0.1", 0)));
    const uint16_t port = l.local_port();
    CHECK(port != 0);

    // 1 Mo dans un sens, 1 Mo dans l'autre : exerce les envois partiels.
    std::vector<unsigned char> out(1 << 20), back(1 << 20);
    for (size_t i = 0; i < out.size(); ++i) out[i] = (unsigned char)(i * 31 + 7);
    std::thread client([&] {
        TcpSocket c;
        CHECK(c.connect(Endpoint("127.0.0.1", port), 2000));
        CHECK(c.send_all(out.data(), out.size(), 2000));
        CHECK(c.recv_all(back.data(), back.size(), 2000));
    });
    Endpoint peer;
    TcpSocket s = l.accept(2000, &peer);
    CHECK(s.valid() && peer.host == "127.0.0.1");
    std::vector<unsigned char> in(out.size());
    CHECK(s.recv_all(in.data(), in.size(), 2000));
    CHECK(in == out);
    CHECK(s.send_all(in.data(), in.size(), 2000));
    client.join();
    CHECK(back == out);

    unsigned char b;
    CHECK(s.recv(&b, 1, 100) == -1);           // le client est parti
    CHECK(!s.valid() && !s.error().empty());

    TcpSocket refused;                          // plus personne n'ecoute
    l.close();
    CHECK(!refused.connect(Endpoint("127.0.0.1", port), 1000));
    CHECK(!refused.error().empty());
    CHECK(!TcpSocket().connect(Endpoint("hote.inexistant.invalid", 1), 500));
}

static void test_udp() {
    UdpSocket a, b;
    CHECK(a.bind(Endpoint("127.0.0.1", 0)) && b.bind(Endpoint("127.0.0.1", 0)));
    Endpoint from;
    char buf[UdpSocket::kSafePayload];
    CHECK(b.recv_from(buf, sizeof buf, from, 50) == 0);   // rien : delai ecoule
    const char msg[] = "commande 42";
    CHECK(a.send_to(msg, sizeof msg, Endpoint("127.0.0.1", b.local_port())) == long(sizeof msg));
    CHECK(b.recv_from(buf, sizeof buf, from, 1000) == long(sizeof msg));
    CHECK(std::strcmp(buf, msg) == 0);
    CHECK(from.port == a.local_port());
}

static void test_multicast() {
    const Endpoint group("239.255.42.99", 0);
    UdpSocket tmp;                              // port libre pour le groupe
    tmp.bind(Endpoint("127.0.0.1", 0));
    const Endpoint g(group.host, tmp.local_port());
    tmp.close();

    // Deux abonnes sur le meme port : RAVEN espionne a cote du vrai consommateur.
    MulticastSocket consumer, spy, sender;
    if (!consumer.join(g, "127.0.0.1") || !spy.join(g, "127.0.0.1") ||
        !sender.open_sender(g, "127.0.0.1", 1, true)) {
        std::printf("multicast indisponible sur ce poste, test saute : %s%s%s\n",
                    consumer.error().c_str(), spy.error().c_str(), sender.error().c_str());
        return;
    }
    const char msg[] = "trame multicast";
    CHECK(sender.send(msg, sizeof msg) == long(sizeof msg));
    char buf[64];
    Endpoint from;
    CHECK(consumer.recv_from(buf, sizeof buf, from, 1000) == long(sizeof msg));
    CHECK(std::strcmp(buf, msg) == 0);
    CHECK(spy.recv_from(buf, sizeof buf, from, 1000) == long(sizeof msg));
    CHECK(std::strcmp(buf, msg) == 0);
}

int main() {
    CHECK(init());
    test_endpoint();
    test_tcp();
    test_udp();
    test_multicast();
    std::printf(g_failed ? "%d echec(s)\n" : "tous les tests reseau passent\n", g_failed);
    return g_failed ? 1 : 0;
}
