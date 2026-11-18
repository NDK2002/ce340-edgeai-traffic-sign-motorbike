# Model mock lấy trực tiếp từ 01_dataset/mock_assets (một nguồn duy nhất, không copy).
# Model thật của Sơn ([S2]) đặt ở 04_tinyml_optimization/ rồi khai báo trong models.h.
idf_component_register(
    SRCS "main.cpp"
    INCLUDE_DIRS "." "../../../01_dataset/mock_assets" "../../../04_tinyml_optimization"
    REQUIRES espressif__esp-tflite-micro espressif__esp32-camera esp_timer esp_psram
             fatfs sdmmc esp_driver_sdmmc esp_driver_tsens
)
