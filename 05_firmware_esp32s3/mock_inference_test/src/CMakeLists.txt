# Model mock lấy trực tiếp từ 01_dataset/mock_assets (một nguồn duy nhất, không copy).
# Khi có model thật từ [S2], đổi INCLUDE_DIRS sang 04_tinyml_optimization/.
idf_component_register(
    SRCS "main.cpp"
    INCLUDE_DIRS "." "../../../01_dataset/mock_assets"
    REQUIRES espressif__esp-tflite-micro espressif__esp32-camera esp_timer esp_psram
)
