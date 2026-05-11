idf_component_register(
    SRCS
        "main.c"
        "camera/camera_capture.c"
        "network/http_camera_server.c"
        "network/wifi_station.c"
    INCLUDE_DIRS
        "."
        "camera"
        "network"
    REQUIRES
        esp_video
        esp_hosted
        esp_wifi_remote
)

