#include <stdio.h>

void print_array(int arr[], int size) {
    for (int i = 0; i < size; i++) {
        printf("%d ", arr[i]);
    }
    printf("\n");
}

int diff_array(int arr1[], int arr2[], int size1, int size2) {
    int diff = 0;
    int min_size = size1 < size2 ? size1 : size2;
    for (int i = 0; i < min_size; i++) {
        diff += arr1[i] - arr2[i];
    }
    for (int i = min_size; i < size1; i++) {
        diff += arr1[i];
    }
    for (int i = min_size; i < size2; i++) {
        diff -= arr2[i];
    }
    return diff;
}

int sum_array(int arr[], int size) {
    int sum = 0;
    for (int i = 0; i < size; i++) {
        sum += arr[i];
    }
    return sum;
}