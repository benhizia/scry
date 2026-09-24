#pragma once
#include <iostream>

/// Class with static members and friend functions
class Counter {
private:
    // Instance data
    int value_;
    std::string name_;
    
    // Static class data
    static int total_instances_;
    static int max_value_seen_;
    
public:
    // Constructor
    Counter(const std::string& name, int initial_value = 0);
    
    // Destructor
    ~Counter();
    
    // Instance methods
    void increment();
    void decrement();
    int get_value() const;
    
    // Static methods
    static int get_total_instances();
    static int get_max_value();
    static void reset_statistics();
    
    // Friend functions
    friend std::ostream& operator<<(std::ostream& os, const Counter& counter);
    friend Counter operator+(const Counter& lhs, const Counter& rhs);
    friend bool operator==(const Counter& lhs, const Counter& rhs);
    
    // Friend class
    friend class CounterManager;
};

/// Friend class that can access private members
class CounterManager {
private:
    // Array of managed counters
    Counter* counters_[10];
    int counter_count_;
    
    // Manager statistics
    static CounterManager* instance_;
    
public:
    CounterManager();
    ~CounterManager();
    
    // Singleton access
    static CounterManager* get_instance();
    
    // Counter management
    void add_counter(Counter* counter);
    void remove_counter(Counter* counter);
    
    // Direct access to private Counter members
    void reset_all_counters();
    int get_total_value() const;
};

/// Class with constant static members
class Constants {
public:
    // Compile-time constants
    static const int MAX_BUFFER_SIZE = 1024;
    static constexpr double PI = 3.14159265359;
    static constexpr float EPSILON = 1e-6f;
    
    // Static data initialized at runtime
    static std::string application_name_;
    static bool debug_enabled_;
    
private:
    // Private constructor to prevent instantiation
    Constants() = delete;
    Constants(const Constants&) = delete;
    Constants& operator=(const Constants&) = delete;
};