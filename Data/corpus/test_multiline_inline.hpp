#pragma once

/// Test struct for multi-line inline comments
struct MultilineInlineTest {
    int value; // Single line comment
    double price; /* Single line block */
    bool flag; /* Multi-line
                  comment for flag */
    char type; ///< Doxygen style
};