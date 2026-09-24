#pragma once

/// Class with constructors and member functions
class Calculator {
private:
    // Internal state value
    int state_;
    
    // Configuration flag
    bool debug_mode_;

public:
    // Default constructor
    Calculator();
    
    // Parameterized constructor
    Calculator(int initial_state, bool debug = false);
    
    // Copy constructor
    Calculator(const Calculator& other);
    
    // Member functions
    int add(int a, int b);
    void reset();
    bool is_debug() const;
    
    // Static member
    static int instance_count_;
};