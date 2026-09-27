// raven-view : le visualiseur. Se connecte a raven.exe, le pilote, et peut
// etre ferme ou relance a tout moment sans toucher a l'enregistrement.
//
//   raven-view [--host 127.0.0.1] [--port 47800]
//   raven-view --headless <images>        (sans fenetre : tests)
//
// Backend : Win32 + DirectX 11 sous Windows, GLFW + OpenGL 3 ailleurs.
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <string>
#include <thread>

#include "imgui.h"
#include "options.h"
#include "ui.h"

using namespace raven;


static bool parse(int argc, char** argv, Options& o) {
    for (int i = 1; i < argc; ++i) {
        const std::string a = argv[i];
        if (i + 1 >= argc) return false;
        if (a == "--host") o.host = argv[++i];
        else if (a == "--port") o.port = std::atoi(argv[++i]);
        else if (a == "--headless") o.headless = std::atoi(argv[++i]);
        else if (a == "--screenshot") o.screenshot = argv[++i];
        else if (a == "--frames") o.frames = std::atoi(argv[++i]);
        else return false;
    }
    return true;
}

// Sans fenetre ni rendu : execute l'IHM image par image. Code de sortie 0 si
// le descripteur a ete recu.
static int run_headless(Client& client, UiState& ui, int images) {
    ImGuiIO& io = ImGui::GetIO();
    io.DisplaySize = ImVec2(1400, 900);
    io.Fonts->Build();
    for (int i = 0; i < images; ++i) {
        io.DeltaTime = 1.0f / 60;
        client.tick();
        ImGui::NewFrame();
        draw(client, ui);
        ImGui::Render();
        std::this_thread::sleep_for(std::chrono::milliseconds(16));
    }
    std::printf("headless : %s, etat %s, %llu trames, %zu valeurs observees\n",
                client.ready() ? "connecte" : "non connecte", client.state.c_str(),
                (unsigned long long)client.frames, client.values.size());
    return client.ready() ? 0 : 1;
}

int run_window(Client& client, UiState& ui, const Options& o);   // backend

int main(int argc, char** argv) {
    Options o;
    if (!parse(argc, argv, o)) {
        std::printf("usage : raven-view [--host H] [--port P] [--headless N]\n");
        return 2;
    }
    net_init();
    Client client;
    client.set_address(o.host, o.port);
    UiState ui;
    ImGui::CreateContext();
    ImGui::GetIO().IniFilename = nullptr;
    ImGui::StyleColorsDark();
    const int rc = o.headless > 0 ? run_headless(client, ui, o.headless) : run_window(client, ui, o);
    ImGui::DestroyContext();
    return rc;
}
