/*Test C source file to test patching.*/

#include <stdio.h>
#include <stdlib.h>

// Function to add two integers
int add(int a, int b) {
    return a + b;
}

// Function to subtract two integers  
int subtract(int a, int b) {
    return a - b;
}

// Function to multiply two integers
int multiply(int a, int b) {
    return a * b;
}

// Function to divide two integers
float divide(int a, int b) {
    return (float)a / b;
}

int main() {
    int x = 10;
    int y = 5;

    printf("Testing basic arithmetic operations:\n");
    printf("x = %d, y = %d\n", x, y);
    printf("Addition: %d\n", add(x, y));
    printf("Subtraction: %d\n", subtract(x, y));
    printf("Multiplication: %d\n", multiply(x, y));
    printf("Division: %.2f\n", divide(x, y));

    return 0;
}