// Fichier d'enregistrement .rvn : auto-descriptif et a enregistrements fixes.
//
//   RAVEN-RVN 1
//   <texte complet du .rvndesc>             (de 'rvndesc 1' a 'end')
//   select <canal> <champ>                  (une ligne par champ enregistre)
//   trigger <texte libre>                   (condition de depart, pour memoire)
//   record_size <octets>
//   data
//   <enregistrements binaires>
//
// Chaque enregistrement : numero de trame (u64), horodatage (u64 ns), puis les
// octets de chaque champ selectionne, dans l'ordre des lignes 'select'. La
// taille fixe rend la n-ieme trame accessible par un simple calcul, et un
// fichier interrompu reste lisible jusqu'au dernier enregistrement complet.
// Un trou dans les numeros de trame est une perte.
#pragma once
#include <cstdio>
#include <string>
#include <vector>

#include "raven/descriptor.h"

namespace raven {

class RvnWriter {
public:
    ~RvnWriter() { close(); }
    bool open(const std::string& path, const Descriptor& d, const std::vector<FieldRef>& sel,
              const std::string& trigger, std::string& error);
    // 'frame' est la trame complete, de taille d.frame_size().
    bool write(uint64_t frame_no, uint64_t t_ns, const unsigned char* frame);
    void close();

    bool is_open() const { return f_ != nullptr; }
    uint64_t records() const { return records_; }
    uint64_t bytes() const { return bytes_; }
    uint32_t record_size() const { return record_size_; }
    const std::string& path() const { return path_; }

private:
    struct Range { uint32_t offset, size; };
    std::FILE* f_ = nullptr;
    std::vector<Range> ranges_;
    std::vector<unsigned char> buf_;
    uint32_t record_size_ = 0;
    uint64_t records_ = 0, bytes_ = 0;
    std::string path_;
};

class RvnReader {
public:
    ~RvnReader() { if (f_) std::fclose(f_); }
    bool open(const std::string& path, std::string& error);

    const Descriptor& descriptor() const { return desc_; }
    const std::vector<FieldRef>& selection() const { return sel_; }
    const std::string& trigger() const { return trigger_; }
    uint64_t count() const { return count_; }           // enregistrements complets

    // Lit l'enregistrement n. 'fields' recoit, pour chaque champ selectionne,
    // un pointeur sur ses octets (valide jusqu'au prochain appel).
    bool read(uint64_t n, uint64_t& frame_no, uint64_t& t_ns,
              std::vector<const unsigned char*>& fields);

private:
    std::FILE* f_ = nullptr;
    Descriptor desc_;
    std::vector<FieldRef> sel_;
    std::vector<uint32_t> field_pos_;
    std::string trigger_;
    long long data_start_ = 0;
    uint32_t record_size_ = 0;
    uint64_t count_ = 0;
    std::vector<unsigned char> buf_;
};

} // namespace raven
