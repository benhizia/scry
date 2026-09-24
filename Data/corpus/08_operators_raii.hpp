#pragma once
#include <memory>
#include <mutex>
#include <string>
#include <sys/types.h>  // ssize_t (POSIX)

/// Class demonstrating operator overloading and RAII
class SmartPointer {
private:
    // Raw pointer being managed
    void* ptr_;
    
    // Reference count for shared ownership
    int* ref_count_;
    
    // Mutex for thread safety
    mutable std::mutex* mutex_;
    
    // Cleanup function pointer
    void (*deleter_)(void*);

public:
    // Constructor
    SmartPointer(void* ptr, void (*deleter)(void*) = nullptr);
    
    // Copy constructor
    SmartPointer(const SmartPointer& other);
    
    // Move constructor
    SmartPointer(SmartPointer&& other) noexcept;
    
    // Destructor (RAII cleanup)
    ~SmartPointer();
    
    // Assignment operators
    SmartPointer& operator=(const SmartPointer& other);
    SmartPointer& operator=(SmartPointer&& other) noexcept;
    
    // Dereference operators
    void* operator*() const;
    void* operator->() const;
    
    // Comparison operators
    bool operator==(const SmartPointer& other) const;
    bool operator!=(const SmartPointer& other) const;
    bool operator<(const SmartPointer& other) const;
    
    // Boolean conversion
    explicit operator bool() const;
    
    // Array access operator
    void* operator[](size_t index) const;
    
    // Reference count
    int use_count() const;
    bool unique() const;
    
    // Reset the pointer
    void reset(void* new_ptr = nullptr);
    
    // Release ownership
    void* release();
};

/// RAII resource management class
class FileHandle {
private:
    // File descriptor or handle
    int file_descriptor_;
    
    // File path for debugging
    std::string file_path_;
    
    // Access mode flags
    int access_mode_;
    
    // State tracking
    bool is_open_;
    mutable bool error_flag_;

public:
    // Constructor automatically opens file
    explicit FileHandle(const std::string& path, int mode = 0);
    
    // Destructor automatically closes file
    ~FileHandle();
    
    // Non-copyable (unique ownership)
    FileHandle(const FileHandle&) = delete;
    FileHandle& operator=(const FileHandle&) = delete;
    
    // Movable
    FileHandle(FileHandle&& other) noexcept;
    FileHandle& operator=(FileHandle&& other) noexcept;
    
    // File operations
    ssize_t read(void* buffer, size_t size);
    ssize_t write(const void* buffer, size_t size);
    
    // Status checking
    bool is_valid() const;
    bool has_error() const;
    std::string get_path() const;
    
    // Explicit conversion to file descriptor
    explicit operator int() const;
};

/// Class with comprehensive operator overloading
class Vector3D {
private:
    // 3D coordinates
    double x_;
    double y_;
    double z_;

public:
    // Constructors
    Vector3D() : x_(0), y_(0), z_(0) {}
    Vector3D(double x, double y, double z) : x_(x), y_(y), z_(z) {}
    
    // Arithmetic operators
    Vector3D operator+(const Vector3D& other) const;
    Vector3D operator-(const Vector3D& other) const;
    Vector3D operator*(double scalar) const;
    Vector3D operator/(double scalar) const;
    
    // Compound assignment operators
    Vector3D& operator+=(const Vector3D& other);
    Vector3D& operator-=(const Vector3D& other);
    Vector3D& operator*=(double scalar);
    Vector3D& operator/=(double scalar);
    
    // Unary operators
    Vector3D operator-() const;
    Vector3D& operator++();    // Prefix
    Vector3D operator++(int);  // Postfix
    
    // Access operators
    double& operator[](int index);
    const double& operator[](int index) const;
    
    // Stream operators
    friend std::ostream& operator<<(std::ostream& os, const Vector3D& vec);
    friend std::istream& operator>>(std::istream& is, Vector3D& vec);
    
    // Utility methods
    double magnitude() const;
    Vector3D normalized() const;
    double dot(const Vector3D& other) const;
};