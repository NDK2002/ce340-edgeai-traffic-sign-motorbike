# Dùng lại, không copy:
#   - board_pins.h, models.h      ← mock_inference_test/src (bảng chân và danh sách model chung)
#   - driver OLED/buzzer/LED/icon ← peripherals_test/src     ([H2] của Hôn)
#   - file model .h               ← 04_tinyml_optimization/ (model thật của Sơn) và 01_dataset/mock_assets/
idf_component_register(
    SRCS "main.cpp"
    INCLUDE_DIRS "."
                 "../../mock_inference_test/src"
                 "../../peripherals_test/src"
                 "../../../04_tinyml_optimization"
                 "../../../01_dataset/mock_assets"
    REQUIRES espressif__esp-tflite-micro espressif__esp32-camera esp_timer esp_psram driver
)
