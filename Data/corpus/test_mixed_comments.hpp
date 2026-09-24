#pragma once

/// Test struct for mixed comment scenarios
struct MixedCommentTest {
    // Before line comment
    int value; // Inline comment
    
    /* Block before */
    double price; /* Block inline */
    
    // Multi-line
    // before comment
    bool flag; /* Multi-line
                  inline comment */
    
    // Standalone comment
    char type;
    
    // Combined before + inline
    // This continues the before
    float ratio; // This is inline
};