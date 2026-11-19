idf_component_register(
    SRCS "main.cpp"
    INCLUDE_DIRS "." "../../mock_inference_test/src"
    REQUIRES driver esp_timer esp_psram freertos
)

