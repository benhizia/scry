#pragma once
#include <string>

struct Options {
    std::string host = "127.0.0.1";
    int port = 47800;
    int headless = 0;              // > 0 : nombre d'images sans fenetre
    std::string screenshot;        // capture PPM (backend GLFW), puis sortie
    int frames = 0;                // image de la capture
};
