#include "ui.h"

#include <cstdio>
#include <cstring>

#include "imgui.h"

namespace raven {

static const char* kOps[] = {"==", "!=", "<", "<=", ">", ">="};

static std::string ref_text(FieldRef r) {
    return std::to_string(r.channel) + ":" + std::to_string(r.field);
}

static void toggle(Client& c, const char* cmd, std::set<FieldRef>& set, FieldRef r, const char* id) {
    bool on = set.count(r) != 0;
    ImGui::PushID(id);
    if (ImGui::Checkbox("##t", &on))
        c.send(std::string(cmd) + " " + ref_text(r) + (on ? " 1" : " 0"));
    ImGui::PopID();
}

// Valeur affichee d'un element de champ feuille, ou "..." en attente.
static std::string shown(const Client& c, FieldRef r, const FieldDesc& f, uint32_t index) {
    auto it = c.values.find(r);
    if (it == c.values.end() || it->second.size() < f.bytes()) return "...";
    return format_value(c.desc(), f, it->second.data(), index);
}

// Ligne d'une feuille : valeur, unite, puis les cases de pilotage.
static void leaf_row(Client& c, UiState& ui, FieldRef r, const FieldDesc& f,
                     std::vector<FieldRef>& visible, bool recording) {
    const bool is_array = f.count > 1;
    ImGui::TableNextRow();
    ImGui::TableNextColumn();
    bool open = false;
    ImGuiTreeNodeFlags flags = ImGuiTreeNodeFlags_SpanFullWidth;
    if (!is_array) flags |= ImGuiTreeNodeFlags_Leaf | ImGuiTreeNodeFlags_NoTreePushOnOpen;
    open = ImGui::TreeNodeEx(f.path.c_str(), flags, "%s%s", f.name.c_str(),
                             is_array ? ("[" + std::to_string(f.count) + "]").c_str() : "");
    visible.push_back(r);                  // seules les lignes dessinees sont demandees
    ImGui::TableNextColumn();
    if (!is_array) ImGui::TextUnformatted(shown(c, r, f, 0).c_str());
    ImGui::TableNextColumn();
    ImGui::TextDisabled("%s", f.unit.c_str());
    ImGui::TableNextColumn();
    ImGui::BeginDisabled(recording);
    toggle(c, "rec", c.rec, r, "rec");
    ImGui::EndDisabled();
    ImGui::TableNextColumn();
    toggle(c, "sen", c.sen, r, "sen");
    ImGui::TableNextColumn();
    toggle(c, "trc", c.trc, r, "trc");
    ImGui::TableNextColumn();
    ImGui::PushID("trg");
    if (ImGui::SmallButton("D")) {
        ui.trg_ref = r;
        ui.trg_value = 0;
    }
    if (ImGui::IsItemHovered()) ImGui::SetTooltip("Choisir ce champ comme declencheur");
    ImGui::PopID();
    if (is_array && open) {
        for (uint32_t i = 0; i < f.count; ++i) {
            ImGui::TableNextRow();
            ImGui::TableNextColumn();
            ImGui::TreeNodeEx((void*)(intptr_t)i,
                              ImGuiTreeNodeFlags_Leaf | ImGuiTreeNodeFlags_NoTreePushOnOpen, "[%u]", i);
            ImGui::TableNextColumn();
            ImGui::TextUnformatted(shown(c, r, f, i).c_str());
        }
        ImGui::TreePop();
    }
}

static void field_rows(Client& c, UiState& ui, const ChannelDesc& ch, int idx,
                       std::vector<FieldRef>& visible, bool recording) {
    const FieldDesc& f = ch.fields[size_t(idx)];
    const FieldRef r{ch.id, idx};
    ImGui::PushID(idx);
    if (f.is_leaf()) {
        if (f.kind != Kind::Other) leaf_row(c, ui, r, f, visible, recording);
    } else {
        ImGui::TableNextRow();
        ImGui::TableNextColumn();
        // Arbre paresseux : un noeud replie ne demande ni ne decode rien.
        if (ImGui::TreeNodeEx(f.path.c_str(), ImGuiTreeNodeFlags_SpanFullWidth, "%s", f.name.c_str())) {
            for (int child : f.children) field_rows(c, ui, ch, child, visible, recording);
            ImGui::TreePop();
        }
    }
    ImGui::PopID();
}

// Zone FIXE : la liste des liaisons, identique quel que soit l'onglet actif.
// Elle est au-dessus des onglets et n'en fait pas partie : changer de sens ne
// doit pas faire perdre de vue l'etat des autres liaisons, ni obliger a
// chercher ou l'on change de liaison.
static void links_bar(Client& c, UiState& ui) {
    const std::vector<LinkInfo>& links = c.links();
    if (links.size() < 2 && !links.empty()) {
        // Une seule liaison : rien a choisir, on se contente de la nommer.
        ImGui::TextDisabled("liaison %s", links.front().name.c_str());
        return;
    }
    if (links.empty()) { ImGui::TextDisabled("liaisons : en attente"); return; }
    ImGui::TextUnformatted("Liaisons");
    ImGui::SameLine();
    for (const LinkInfo& l : links) {
        ImGui::SameLine();
        const bool actif = l.current;
        if (actif) ImGui::PushStyleColor(ImGuiCol_Button, ImVec4(0.20f, 0.45f, 0.70f, 1));
        ImGui::PushID(l.index);
        if (ImGui::Button(l.name.c_str())) {
            c.use_link(l.name);
            ui.trg_ref = FieldRef();          // le declencheur visait l'autre liaison
            ui.path_synced = false;
        }
        ImGui::PopID();
        if (actif) ImGui::PopStyleColor();
        if (ImGui::IsItemHovered())
            ImGui::SetTooltip("%s\n%s, %llu trames\n%s", l.name.c_str(), l.state.c_str(),
                              (unsigned long long)l.frames, l.source.c_str());
        // L'etat de chaque liaison reste lisible sans y basculer.
        ImGui::SameLine();
        if (l.state == "recording") ImGui::TextColored(ImVec4(1, 0.25f, 0.25f, 1), "[enr]");
        else if (l.state == "armed") ImGui::TextColored(ImVec4(1, 0.7f, 0.1f, 1), "[arme]");
        else ImGui::TextDisabled("[repos]");
    }
}

// Libelle d'un onglet : le sens quand il y en a un, le nom du canal sinon.
// En relais, un sens porte un seul type de message : un onglet par sens est
// donc exactement un onglet par canal.
static std::string tab_label(Client& c, const ChannelDesc& ch) {
    const std::string dir = c.channel_direction(ch.id);
    return dir.empty() ? ch.name : dir + "  " + ch.name;
}

static void tree_panel(Client& c, UiState& ui, const ChannelDesc& only) {
    std::vector<FieldRef> visible;
    const bool recording = c.state != "idle";
    const ImGuiTableFlags tf = ImGuiTableFlags_RowBg | ImGuiTableFlags_BordersInnerV |
                               ImGuiTableFlags_Resizable | ImGuiTableFlags_ScrollY;
    if (ImGui::BeginTable("tree", 7, tf)) {
        ImGui::TableSetupScrollFreeze(0, 1);
        ImGui::TableSetupColumn("Champ", ImGuiTableColumnFlags_WidthStretch, 3.0f);
        ImGui::TableSetupColumn("Valeur", ImGuiTableColumnFlags_WidthStretch, 2.0f);
        ImGui::TableSetupColumn("Unite", ImGuiTableColumnFlags_WidthFixed, 45);
        ImGui::TableSetupColumn("Enr.", ImGuiTableColumnFlags_WidthFixed, 35);
        ImGui::TableSetupColumn("Sent.", ImGuiTableColumnFlags_WidthFixed, 35);
        ImGui::TableSetupColumn("Trace", ImGuiTableColumnFlags_WidthFixed, 35);
        ImGui::TableSetupColumn("Decl.", ImGuiTableColumnFlags_WidthFixed, 35);
        ImGui::TableHeadersRow();
        // Un seul canal par onglet : la racine n'a plus a etre un noeud, les
        // champs sont directement a l'ecran.
        ImGui::PushID(only.id);
        for (int root : only.roots) field_rows(c, ui, only, root, visible, recording);
        ImGui::PopID();
        ImGui::EndTable();
    }
    // Seuls les champs de l'onglet visible sont demandes a raven.exe : les
    // autres sens ne coutent rien tant qu'on ne les regarde pas.
    c.set_watch(visible);
}

static void recording_panel(Client& c, UiState& ui) {
    const bool idle = c.state == "idle";
    ImVec4 color = idle ? ImVec4(0.6f, 0.6f, 0.6f, 1) : c.state == "armed" ? ImVec4(1, 0.7f, 0.1f, 1)
                                                                           : ImVec4(1, 0.25f, 0.25f, 1);
    ImGui::TextColored(color, "%s", idle ? "AU REPOS" : c.state == "armed" ? "ARME" : "ENREGISTREMENT");
    ImGui::SameLine();
    ImGui::Text("  %zu champ(s) choisi(s)", c.rec.size());
    if (!ui.path_synced && !c.path.empty()) {
        std::snprintf(ui.path, sizeof ui.path, "%s", c.path.c_str());
        ui.path_synced = true;
    }
    ImGui::BeginDisabled(!idle);
    ImGui::SetNextItemWidth(-90);
    ImGui::InputText("##path", ui.path, sizeof ui.path);
    ImGui::SameLine();
    if (ImGui::Button("Fichier")) c.send(std::string("path ") + ui.path);
    if (ImGui::IsItemHovered()) ImGui::SetTooltip("%%t est remplace par la date et l'heure");
    if (ImGui::Button("Tout choisir")) c.send("rec_all 1");
    ImGui::SameLine();
    if (ImGui::Button("Aucun")) c.send("rec_all 0");
    ImGui::EndDisabled();
    ImGui::SameLine();
    if (idle) {
        ImGui::BeginDisabled(c.rec.empty());
        if (ImGui::Button("Armer")) c.send("arm");
        ImGui::EndDisabled();
    } else if (ImGui::Button("Arreter")) {
        c.send("stop");
    }
    if (c.state == "recording") {
        const double b = double(c.rec_bytes);
        ImGui::Text("%llu trames, %.1f %s", (unsigned long long)c.rec_frames,
                    b < 1e6 ? b / 1e3 : b < 1e9 ? b / 1e6 : b / 1e9, b < 1e6 ? "Ko" : b < 1e9 ? "Mo" : "Go");
    }
    if (!c.message.empty()) ImGui::TextWrapped("%s", c.message.c_str());
}

static void trigger_panel(Client& c, UiState& ui) {
    const Descriptor& d = c.desc();
    if (c.trg_active) ImGui::Text("Actif : %s %s %s", d.full_path(c.trg_ref).c_str(), c.trg_op.c_str(),
                                  format_number(d, *d.field(c.trg_ref), c.trg_value).c_str());
    else ImGui::TextDisabled("Aucun : l'enregistrement demarre des qu'on arme.");
    const FieldDesc* f = d.field(ui.trg_ref);
    if (!f) {
        ImGui::TextDisabled("Bouton D d'un champ pour le choisir.");
    } else {
        ImGui::Text("%s", d.full_path(ui.trg_ref).c_str());
        ImGui::SetNextItemWidth(60);
        ImGui::Combo("##op", &ui.trg_op, kOps, 6);
        ImGui::SameLine();
        ImGui::SetNextItemWidth(160);
        const EnumDesc* e = d.enum_of(*f);
        if (e && !e->items.empty()) {
            // Les valeurs possibles viennent du descripteur : pas d'entier a deviner.
            const char* cur = e->name_of(int64_t(ui.trg_value));
            if (ImGui::BeginCombo("##val", cur ? cur : "?")) {
                for (const EnumItem& it : e->items)
                    if (ImGui::Selectable(it.name.c_str(), int64_t(ui.trg_value) == it.value))
                        ui.trg_value = double(it.value);
                ImGui::EndCombo();
            }
        } else if (f->kind == Kind::Bool) {
            int b = ui.trg_value != 0;
            const char* names[] = {"false", "true"};
            if (ImGui::Combo("##val", &b, names, 2)) ui.trg_value = b;
        } else {
            ImGui::InputDouble("##val", &ui.trg_value);
        }
        ImGui::SameLine();
        if (ImGui::Button("Appliquer")) {
            char buf[64];
            std::snprintf(buf, sizeof buf, "%.17g", ui.trg_value);
            c.send("trg " + ref_text(ui.trg_ref) + " " + kOps[ui.trg_op] + " " + buf);
        }
    }
    if (c.trg_active && ImGui::Button("Supprimer le declencheur")) c.send("trg off");
}

static void sentinel_panel(Client& c) {
    const Descriptor& d = c.desc();
    if (c.sen.empty()) { ImGui::TextDisabled("Case Sent. d'un champ pour le surveiller."); return; }
    if (ImGui::Button("Remettre a zero")) {
        c.send("sen_reset");
        c.sentinel_last.clear();
        c.events.clear();
    }
    if (ImGui::BeginTable("sen", 3, ImGuiTableFlags_RowBg | ImGuiTableFlags_BordersInnerV)) {
        ImGui::TableSetupColumn("Champ");
        ImGui::TableSetupColumn("Changements", ImGuiTableColumnFlags_WidthFixed, 90);
        ImGui::TableSetupColumn("Dernier");
        ImGui::TableHeadersRow();
        for (const FieldRef& r : c.sen) {
            const FieldDesc& f = *d.field(r);
            auto it = c.sentinel_last.find(r);
            ImGui::TableNextRow();
            ImGui::TableNextColumn();
            ImGui::TextUnformatted(d.full_path(r).c_str());
            ImGui::TableNextColumn();
            // Un changement reste affiche meme s'il n'a dure qu'une trame.
            if (it != c.sentinel_last.end()) ImGui::TextColored(ImVec4(1, 0.8f, 0.2f, 1), "%llu",
                                                               (unsigned long long)it->second.count);
            else ImGui::TextDisabled("0");
            ImGui::TableNextColumn();
            if (it != c.sentinel_last.end())
                ImGui::Text("%s -> %s  (trame %llu)", format_number(d, f, it->second.old_value).c_str(),
                            format_number(d, f, it->second.new_value).c_str(),
                            (unsigned long long)it->second.frame);
        }
        ImGui::EndTable();
    }
    if (ImGui::TreeNode("Journal")) {
        for (auto it = c.events.rbegin(); it != c.events.rend(); ++it) {
            const FieldDesc& f = *d.field(it->ref);
            ImGui::Text("trame %llu  %s : %s -> %s", (unsigned long long)it->frame, d.full_path(it->ref).c_str(),
                        format_number(d, f, it->old_value).c_str(), format_number(d, f, it->new_value).c_str());
        }
        ImGui::TreePop();
    }
}

static void trace_panel(Client& c) {
    const Descriptor& d = c.desc();
    if (c.trc.empty()) { ImGui::TextDisabled("Case Trace d'un champ pour le tracer."); return; }
    for (const FieldRef& r : c.trc) {
        auto it = c.traces.find(r);
        if (it == c.traces.end() || it->second.values.empty()) {
            ImGui::TextDisabled("%s : en attente", d.full_path(r).c_str());
            continue;
        }
        const std::vector<float> v(it->second.values.begin(), it->second.values.end());
        float lo = v[0], hi = v[0];
        for (float x : v) { lo = x < lo ? x : lo; hi = x > hi ? x : hi; }
        const std::string label = d.full_path(r) + " = " + format_number(d, *d.field(r), v.back());
        ImGui::PlotLines(("##" + ref_text(r)).c_str(), v.data(), int(v.size()), 0, label.c_str(),
                         lo, hi == lo ? lo + 1 : hi, ImVec2(-1, 70));
    }
}

void draw(Client& c, UiState& ui) {
    const ImGuiViewport* vp = ImGui::GetMainViewport();
    ImGui::SetNextWindowPos(vp->WorkPos);
    ImGui::SetNextWindowSize(vp->WorkSize);
    ImGui::Begin("RAVEN", nullptr, ImGuiWindowFlags_NoDecoration | ImGuiWindowFlags_NoMove |
                                   ImGuiWindowFlags_NoSavedSettings);
    // Barre d'etat.
    if (!c.connected()) {
        ImGui::TextColored(ImVec4(1, 0.4f, 0.4f, 1), "raven.exe injoignable sur %s, nouvel essai...",
                           c.address().c_str());
        ImGui::End();
        return;
    }
    if (!c.ready()) { ImGui::Text("Connexion a %s...", c.address().c_str()); ImGui::End(); return; }
    ImGui::Text("raven %s", c.address().c_str());
    ImGui::SameLine();
    if (c.source_ok) ImGui::TextColored(ImVec4(0.3f, 0.9f, 0.3f, 1), "  source OK");
    else ImGui::TextColored(ImVec4(1, 0.5f, 0.2f, 1), "  source absente");
    ImGui::SameLine();
    ImGui::Text("  trame %llu   recues %llu   perdues %llu", (unsigned long long)c.last,
                (unsigned long long)c.frames, (unsigned long long)c.lost);
    ImGui::SameLine();
    ImGui::Checkbox("Pause vue", &c.paused);
    if (ImGui::IsItemHovered()) ImGui::SetTooltip("Gele les valeurs affichees ; raven continue d'acquerir et d'enregistrer");
    if (!c.last_error.empty()) {
        ImGui::TextColored(ImVec4(1, 0.4f, 0.4f, 1), "%s", c.last_error.c_str());
        ImGui::SameLine();
        if (ImGui::SmallButton("x")) c.last_error.clear();
    }
    // Zone fixe : les liaisons. Au-dessus des onglets, donc stable.
    links_bar(c, ui);
    ImGui::Separator();

    const float right = ImGui::GetContentRegionAvail().x * 0.42f;
    ImGui::BeginChild("left", ImVec2(-right, 0));
    const std::vector<ChannelDesc>& channels = c.desc().channels();
    if (channels.empty()) {
        ImGui::TextDisabled("aucun canal");
    } else if (ImGui::BeginTabBar("sens")) {
        for (const ChannelDesc& ch : channels) {
            const std::string label = tab_label(c, ch);
            if (ImGui::BeginTabItem(label.c_str())) {
                tree_panel(c, ui, ch);
                ImGui::EndTabItem();
            }
        }
        ImGui::EndTabBar();
    }
    ImGui::EndChild();
    ImGui::SameLine();
    ImGui::BeginChild("right", ImVec2(0, 0));
    if (ImGui::CollapsingHeader("Enregistrement", ImGuiTreeNodeFlags_DefaultOpen)) recording_panel(c, ui);
    if (ImGui::CollapsingHeader("Declencheur", ImGuiTreeNodeFlags_DefaultOpen)) trigger_panel(c, ui);
    if (ImGui::CollapsingHeader("Sentinelles", ImGuiTreeNodeFlags_DefaultOpen)) sentinel_panel(c);
    if (ImGui::CollapsingHeader("Traces", ImGuiTreeNodeFlags_DefaultOpen)) trace_panel(c);
    ImGui::EndChild();
    ImGui::End();
}

} // namespace raven
