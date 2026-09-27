// IHM de raven-view, independante du backend graphique : draw() est appele a
// chaque image entre NewFrame et Render.
#pragma once
#include "client.h"

namespace raven {

struct UiState {
    // Editeur du declencheur, avant envoi a raven.exe.
    FieldRef trg_ref;
    int trg_op = 0;
    double trg_value = 0;
    char path[512] = "";
    bool path_synced = false;
};

void draw(Client& c, UiState& ui);

} // namespace raven
