#include "camera_capture.h"

#include <errno.h>
#include <stdbool.h>
#include <fcntl.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <unistd.h>

#include "camera_board_config.h"
#include "esp_check.h"
#include "esp_err.h"
#include "esp_log.h"
#include "esp_video_init.h"
#include "linux/videodev2.h"

static const char *TAG = "camera_capture";
#define CAMERA_BUFFER_COUNT 2

typedef struct {
    void *start;
    size_t length;
} camera_buffer_t;

static int s_video_fd = -1;
static camera_buffer_t s_buffers[CAMERA_BUFFER_COUNT] = {0};
static bool s_streaming = false;

static esp_err_t log_video_capabilities(int fd)
{
    struct v4l2_capability capability = {0};

    if (ioctl(fd, VIDIOC_QUERYCAP, &capability) != 0) {
        ESP_LOGE(TAG, "VIDIOC_QUERYCAP failed: errno=%d (%s)", errno, strerror(errno));
        return ESP_FAIL;
    }

    ESP_LOGI(TAG, "Video driver: %s", capability.driver);
    ESP_LOGI(TAG, "Video card: %s", capability.card);
    ESP_LOGI(TAG, "Bus info: %s", capability.bus_info);
    ESP_LOGI(TAG, "Capabilities: 0x%08lx", capability.capabilities);

    return ESP_OK;
}

static esp_err_t log_video_format(int fd)
{
    struct v4l2_format format = {
        .type = V4L2_BUF_TYPE_VIDEO_CAPTURE,
    };

    if (ioctl(fd, VIDIOC_G_FMT, &format) != 0) {
        ESP_LOGE(TAG, "VIDIOC_G_FMT failed: errno=%d (%s)", errno, strerror(errno));
        return ESP_FAIL;
    }

    ESP_LOGI(TAG,
             "Frame format: %lux%lu fourcc=0x%08lx size=%lu bytes",
             format.fmt.pix.width,
             format.fmt.pix.height,
             format.fmt.pix.pixelformat,
             format.fmt.pix.sizeimage);

    return ESP_OK;
}

static esp_err_t init_capture_buffers(int fd)
{
    struct v4l2_requestbuffers req = {
        .count = CAMERA_BUFFER_COUNT,
        .type = V4L2_BUF_TYPE_VIDEO_CAPTURE,
        .memory = V4L2_MEMORY_MMAP,
    };

    if (ioctl(fd, VIDIOC_REQBUFS, &req) != 0) {
        ESP_LOGE(TAG, "VIDIOC_REQBUFS failed: errno=%d (%s)", errno, strerror(errno));
        return ESP_FAIL;
    }

    if (req.count < CAMERA_BUFFER_COUNT) {
        ESP_LOGE(TAG, "Video driver allocated only %lu buffers", req.count);
        return ESP_ERR_NO_MEM;
    }

    for (uint32_t i = 0; i < CAMERA_BUFFER_COUNT; ++i) {
        struct v4l2_buffer buffer = {
            .type = V4L2_BUF_TYPE_VIDEO_CAPTURE,
            .memory = V4L2_MEMORY_MMAP,
            .index = i,
        };

        if (ioctl(fd, VIDIOC_QUERYBUF, &buffer) != 0) {
            ESP_LOGE(TAG, "VIDIOC_QUERYBUF[%lu] failed: errno=%d (%s)", i, errno, strerror(errno));
            return ESP_FAIL;
        }

        s_buffers[i].length = buffer.length;
        s_buffers[i].start = mmap(NULL, buffer.length, PROT_READ | PROT_WRITE, MAP_SHARED, fd, buffer.m.offset);
        if (s_buffers[i].start == MAP_FAILED) {
            ESP_LOGE(TAG, "mmap[%lu] failed: errno=%d (%s)", i, errno, strerror(errno));
            s_buffers[i].start = NULL;
            s_buffers[i].length = 0;
            return ESP_FAIL;
        }

        if (ioctl(fd, VIDIOC_QBUF, &buffer) != 0) {
            ESP_LOGE(TAG, "VIDIOC_QBUF[%lu] failed: errno=%d (%s)", i, errno, strerror(errno));
            return ESP_FAIL;
        }
    }

    ESP_LOGI(TAG, "Allocated %lu capture buffers", CAMERA_BUFFER_COUNT);
    return ESP_OK;
}

static esp_err_t start_streaming(int fd)
{
    enum v4l2_buf_type type = V4L2_BUF_TYPE_VIDEO_CAPTURE;

    if (ioctl(fd, VIDIOC_STREAMON, &type) != 0) {
        ESP_LOGE(TAG, "VIDIOC_STREAMON failed: errno=%d (%s)", errno, strerror(errno));
        return ESP_FAIL;
    }

    s_streaming = true;
    ESP_LOGI(TAG, "Camera streaming started");
    return ESP_OK;
}

esp_err_t camera_capture_init(void)
{
    esp_video_init_csi_config_t csi_config = {
        .sccb_config = {
            .init_sccb = true,
            .i2c_config = {
                .port = CAMERA_SCCB_I2C_PORT,
                .scl_pin = CAMERA_SCCB_SCL_PIN,
                .sda_pin = CAMERA_SCCB_SDA_PIN,
            },
            .freq = CAMERA_SCCB_FREQ_HZ,
        },
        .reset_pin = CAMERA_RESET_PIN,
        .pwdn_pin = CAMERA_PWDN_PIN,
        .dont_init_ldo = false,
    };

    esp_video_init_config_t video_config = {
        .csi = &csi_config,
    };

    esp_err_t ret = esp_video_init(&video_config);
    if (ret != ESP_OK) {
        ESP_LOGE(TAG, "esp_video_init failed: %s", esp_err_to_name(ret));
        return ret;
    }

    s_video_fd = open(CAMERA_VIDEO_DEVICE, O_RDONLY);
    if (s_video_fd < 0) {
        ESP_LOGE(TAG, "Failed to open %s: errno=%d (%s)", CAMERA_VIDEO_DEVICE, errno, strerror(errno));
        return ESP_FAIL;
    }

    ESP_RETURN_ON_ERROR(log_video_capabilities(s_video_fd), TAG, "Failed to query video device");
    ESP_RETURN_ON_ERROR(log_video_format(s_video_fd), TAG, "Failed to query video format");
    ESP_RETURN_ON_ERROR(init_capture_buffers(s_video_fd), TAG, "Failed to initialize capture buffers");
    ESP_RETURN_ON_ERROR(start_streaming(s_video_fd), TAG, "Failed to start camera streaming");

    ESP_LOGI(TAG, "Camera initialized on %s", CAMERA_VIDEO_DEVICE);
    return ESP_OK;
}

esp_err_t camera_capture_grab_once(void)
{
    if (s_video_fd < 0) {
        return ESP_ERR_INVALID_STATE;
    }

    if (!s_streaming) {
        return ESP_ERR_INVALID_STATE;
    }

    struct v4l2_buffer buffer = {
        .type = V4L2_BUF_TYPE_VIDEO_CAPTURE,
        .memory = V4L2_MEMORY_MMAP,
    };

    if (ioctl(s_video_fd, VIDIOC_DQBUF, &buffer) != 0) {
        ESP_LOGE(TAG, "VIDIOC_DQBUF failed: errno=%d (%s)", errno, strerror(errno));
        return ESP_FAIL;
    }

    ESP_LOGI(TAG, "Captured frame: index=%lu bytes=%lu", buffer.index, buffer.bytesused);

    if (ioctl(s_video_fd, VIDIOC_QBUF, &buffer) != 0) {
        ESP_LOGE(TAG, "VIDIOC_QBUF failed: errno=%d (%s)", errno, strerror(errno));
        return ESP_FAIL;
    }

    return ESP_OK;
}
