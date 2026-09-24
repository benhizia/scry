#pragma once
#include <vector>
#include <memory>
#include <string>

/// Template class with different specializations
template<typename T>
class Container {
private:
    // Dynamic array of elements
    std::vector<T> elements_;
    
    // Current capacity
    size_t capacity_;
    
    // Growth factor
    double growth_factor_;

public:
    Container(size_t initial_capacity = 10);
    
    // Template member functions
    void add(const T& element);
    T get(size_t index) const;
    size_t size() const;
    
    // Template static member
    static constexpr size_t default_size = 100;
};

/// Template specialization for pointers
template<typename T>
class Container<T*> {
private:
    // Array of pointers
    std::vector<std::unique_ptr<T>> ptr_elements_;
    
    // Ownership flag
    bool owns_elements_;

public:
    Container(bool owns = true);
    void add_ptr(T* ptr);
    T* get_ptr(size_t index) const;
};

/// Non-template class using templates
class StringContainer {
private:
    // Template instantiation
    Container<std::string> strings_;
    
    // Metadata
    std::string container_name_;
    
public:
    explicit StringContainer(const std::string& name);
    void add_string(const std::string& str);
};