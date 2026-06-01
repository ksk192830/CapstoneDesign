#include "http_camera_server.h"

#include <math.h>
#include <stdio.h>
#include <stdlib.h>

#include "camera_capture.h"
#include "driver/jpeg_encode.h"
#include "esp_check.h"
#include "esp_err.h"
#include "esp_http_server.h"
#include "esp_log.h"
#include "motor_control.h"
#include "thermal_task.h"

enum {
    CAMERA_STREAM_WIDTH = 800,
    CAMERA_STREAM_HEIGHT = 640,
    CAMERA_STREAM_JPEG_QUALITY = 40,
};

static const char *TAG = "http_camera_server";
static jpeg_encoder_handle_t s_jpeg_encoder;
static uint8_t *s_jpeg_output_buffer;
static uint32_t s_jpeg_output_buffer_size;

static esp_err_t ensure_jpeg_encoder(void)
{
    if (s_jpeg_encoder != NULL && s_jpeg_output_buffer != NULL) {
        return ESP_OK;
    }

    if (s_jpeg_encoder == NULL) {
        jpeg_encode_engine_cfg_t engine_cfg = {
            .intr_priority = 0,
            .timeout_ms = 5000,
        };
        ESP_RETURN_ON_ERROR(jpeg_new_encoder_engine(&engine_cfg, &s_jpeg_encoder), TAG, "failed to create jpeg encoder");
    }

    if (s_jpeg_output_buffer == NULL) {
        jpeg_encode_memory_alloc_cfg_t mem_cfg = {
            .buffer_direction = JPEG_DEC_ALLOC_OUTPUT_BUFFER,
        };

        size_t allocated_size = 0;
        s_jpeg_output_buffer = jpeg_alloc_encoder_mem(CAMERA_STREAM_WIDTH * CAMERA_STREAM_HEIGHT * 2, &mem_cfg, &allocated_size);
        ESP_RETURN_ON_FALSE(s_jpeg_output_buffer != NULL, ESP_ERR_NO_MEM, TAG, "failed to allocate jpeg output buffer");
        s_jpeg_output_buffer_size = (uint32_t)allocated_size;
    }

    return ESP_OK;
}

static esp_err_t root_handler(httpd_req_t *req)
{
    const char *body =
        "<!DOCTYPE html>"
        "<html>"
        "<head>"
        "<meta charset='UTF-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1.0'>"
        "<title>ESP32-P4 Camera</title>"
        "<style>"
        "body { font-family: Arial, sans-serif; margin: 20px; background: #f0f0f0; }"
        ".container { max-width: 1200px; margin: 0 auto; background: white; padding: 20px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }"
        "h1 { color: #333; text-align: center; }"
        ".views { display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 16px; align-items: start; }"
        ".panel { min-width: 0; }"
        ".panel h2 { margin: 0 0 8px; font-size: 18px; color: #333; }"
        "img, canvas { display: block; width: 100%; border: 2px solid #ddd; border-radius: 4px; background: #000; }"
        "#thermal { aspect-ratio: 3 / 4; image-rendering: pixelated; }"
        ".info { color: #666; text-align: center; }"
        ".status { padding: 10px; margin: 10px 0; border-radius: 4px; text-align: center; }"
        ".status.ok { background: #d4edda; color: #155724; }"
        ".status.error { background: #f8d7da; color: #721c24; }"
        ".fps { font-weight: bold; color: #007bff; }"
        ".control { margin-top: 18px; padding-top: 16px; border-top: 1px solid #ddd; }"
        ".control-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 12px; align-items: stretch; }"
        ".keys { display: grid; grid-template-columns: repeat(3, 54px); gap: 8px; justify-content: center; align-content: center; }"
        ".key { height: 42px; border: 1px solid #bbb; border-radius: 6px; display: flex; align-items: center; justify-content: center; font-weight: bold; background: #f7f7f7; color: #333; touch-action: none; user-select: none; -webkit-user-select: none; }"
        ".key.active { background: #007bff; border-color: #0056b3; color: white; }"
        ".readout { font-family: monospace; font-size: 14px; line-height: 1.5; background: #111; color: #d7ffd7; padding: 12px; border-radius: 6px; min-height: 116px; white-space: pre-wrap; }"
        ".hint { color: #555; text-align: center; margin: 8px 0 0; }"
        "</style>"
        "</head>"
        "<body>"
        "<div class='container'>"
        "<h1>ESP32-P4 Camera Stream</h1>"
        "<div class='views'>"
        "<div class='panel'>"
        "<h2>Visible Camera</h2>"
        "<img id='stream' width='800' height='640' alt='camera stream'>"
        "</div>"
        "<div class='panel'>"
        "<h2>Thermal Camera</h2>"
        "<canvas id='thermal' width='24' height='32'></canvas>"
        "</div>"
        "</div>"
        "<div class='status ok' id='status'>Connecting...</div>"
        "<div class='info' id='thermalInfo'>Visible: 800x640 MJPEG | Thermal: waiting</div>"
        "<div class='control'>"
        "<h2>Manual Drive</h2>"
        "<div class='control-grid'>"
        "<div>"
        "<div class='keys'>"
        "<div class='key' id='key-q'>Q</div><div class='key' id='key-w'>W</div><div class='key' id='key-e'>E</div>"
        "<div class='key' id='key-a'>A</div><div class='key' id='key-s'>S</div><div class='key' id='key-d'>D</div>"
        "</div>"
        "<div class='hint'>W/S forward/back, A/D strafe, Q/E rotate</div>"
        "</div>"
        "<div class='readout' id='driveInfo'>Drive idle</div>"
        "</div>"
        "</div>"
        "</div>"
        "<script>"
        "const canvas=document.getElementById('thermal');"
        "const ctx=canvas.getContext('2d');"
        "const statusEl=document.getElementById('status');"
        "const thermalInfo=document.getElementById('thermalInfo');"
        "const driveInfo=document.getElementById('driveInfo');"
        "const pressed=new Set();"
        "let driveTimer=null;"
        "let stopSent=true;"
        "document.getElementById('stream').src=location.protocol+'//'+location.hostname+':81/stream.mjpg';"
        "function color(t){"
        " const x=Math.max(0,Math.min(1,t));"
        " const r=Math.round(255*Math.min(1,Math.max(0,1.5*x-0.15)));"
        " const g=Math.round(255*Math.min(1,Math.max(0,1.5-3*Math.abs(x-0.5))));"
        " const b=Math.round(255*Math.min(1,Math.max(0,1.2-1.8*x)));"
        " return [r,g,b];"
        "}"
        "async function drawThermal(){"
        " try{"
        "  const res=await fetch('/thermal/frame',{cache:'no-store'});"
        "  if(!res.ok) throw new Error('HTTP '+res.status);"
        "  const data=await res.json();"
        "  if(!data.temps_c){"
        "   statusEl.className='status ok';"
        "   statusEl.textContent='Thermal warming up...';"
        "   return;"
        "  }"
        "  const temps=data.temps_c;"
        "  let min=Infinity,max=-Infinity;"
        "  for(const v of temps){ if(Number.isFinite(v)){ if(v<min)min=v; if(v>max)max=v; } }"
        "  const span=Math.max(1,max-min);"
        "  const img=ctx.createImageData(24,32);"
        "  for(let i=0;i<768;i++){"
        "   const [r,g,b]=color((temps[i]-min)/span);"
        "   const x=i%32,y=Math.floor(i/32);"
        "   const p=(((31-x)*24)+(23-y))*4;"
        "   img.data[p]=r; img.data[p+1]=g; img.data[p+2]=b; img.data[p+3]=255;"
        "  }"
        "  ctx.putImageData(img,0,0);"
        "  statusEl.className='status ok';"
        "  statusEl.textContent='Connected';"
        "  thermalInfo.textContent='Visible: 800x640 MJPEG | Thermal: '+min.toFixed(1)+'C - '+max.toFixed(1)+'C';"
        " }catch(e){"
        "  statusEl.className='status error';"
        "  statusEl.textContent='Thermal unavailable: '+e.message;"
        " }"
        "}"
        "setInterval(drawThermal,250);"
        "drawThermal();"
        "function driveVector(){"
        " let x=0,y=0,r=0;"
        " if(pressed.has('w')) y+=1;"
        " if(pressed.has('s')) y-=1;"
        " if(pressed.has('d')) x+=1;"
        " if(pressed.has('a')) x-=1;"
        " if(pressed.has('q')) r+=1;"
        " if(pressed.has('e')) r-=1;"
        " const m=Math.max(1,Math.abs(x),Math.abs(y),Math.abs(r));"
        " return {x:x/m,y:y/m,r:r/m};"
        "}"
        "function updateKeys(){"
        " for(const k of ['q','w','e','a','s','d']){"
        "  const el=document.getElementById('key-'+k);"
        "  if(el) el.classList.toggle('active',pressed.has(k));"
        " }"
        "}"
        "async function sendDrive(){"
        " const v=driveVector();"
        " const moving=Math.abs(v.x)+Math.abs(v.y)+Math.abs(v.r)>0;"
        " try{"
        "  if(moving){"
        "   stopSent=false;"
        "   const url='/control/manual?x='+v.x.toFixed(2)+'&y='+v.y.toFixed(2)+'&r='+v.r.toFixed(2)+'&ttl=300';"
        "   const res=await fetch(url,{cache:'no-store'});"
        "   if(!res.ok) throw new Error('HTTP '+res.status);"
        "  }else if(!stopSent){"
        "   stopSent=true;"
        "   const res=await fetch('/control/stop',{cache:'no-store'});"
        "   if(!res.ok) throw new Error('HTTP '+res.status);"
        "  }"
        "  const st=await fetch('/control/status',{cache:'no-store'}).then(r=>r.json());"
        "  driveInfo.textContent='active: '+st.active+'\\nvector x/y/r: '+st.x.toFixed(2)+' / '+st.y.toFixed(2)+' / '+st.r.toFixed(2)+'\\nwheels FL/FR/BL/BR: '+st.wheels.fl.toFixed(2)+' / '+st.wheels.fr.toFixed(2)+' / '+st.wheels.bl.toFixed(2)+' / '+st.wheels.br.toFixed(2)+'\\nduty FL/FR/BL/BR: '+st.duties.fl+' / '+st.duties.fr+' / '+st.duties.bl+' / '+st.duties.br+'\\nenc FL/FR/BL/BR: '+st.encoders.fl+' / '+st.encoders.fr+' / '+st.encoders.bl+' / '+st.encoders.br;"
        " }catch(e){"
        "  driveInfo.textContent='Drive error: '+e.message;"
        " }"
        "}"
        "function ensureDriveTimer(){"
        " if(!driveTimer) driveTimer=setInterval(sendDrive,80);"
        "}"
        "document.addEventListener('keydown',e=>{"
        " const k=e.key.toLowerCase();"
        " if(['q','w','e','a','s','d'].includes(k)){ e.preventDefault(); pressed.add(k); updateKeys(); ensureDriveTimer(); sendDrive(); }"
        "});"
        "document.addEventListener('keyup',e=>{"
        " const k=e.key.toLowerCase();"
        " if(['q','w','e','a','s','d'].includes(k)){ e.preventDefault(); pressed.delete(k); updateKeys(); sendDrive(); }"
        "});"
        "document.querySelectorAll('.key').forEach(el=>{"
        " const k=el.id.replace('key-','');"
        " const press=e=>{ e.preventDefault(); el.setPointerCapture?.(e.pointerId); pressed.add(k); updateKeys(); ensureDriveTimer(); sendDrive(); };"
        " const release=e=>{ e.preventDefault(); pressed.delete(k); updateKeys(); sendDrive(); };"
        " el.addEventListener('pointerdown',press);"
        " el.addEventListener('pointerup',release);"
        " el.addEventListener('pointercancel',release);"
        "});"
        "window.addEventListener('blur',()=>{ pressed.clear(); updateKeys(); sendDrive(); });"
        "setInterval(sendDrive,500);"
        "</script>"
        "</body>"
        "</html>";

    httpd_resp_set_type(req, "text/html; charset=utf-8");
    return httpd_resp_send(req, body, HTTPD_RESP_USE_STRLEN);
}

static esp_err_t capture_raw_handler(httpd_req_t *req)
{
    camera_frame_t frame = {0};
    esp_err_t ret = camera_capture_get_frame(&frame);
    if (ret != ESP_OK) {
        ESP_LOGE(TAG, "Failed to capture frame: %s", esp_err_to_name(ret));
        httpd_resp_send_err(req, HTTPD_500_INTERNAL_SERVER_ERROR, "camera capture failed");
        return ret;
    }

    httpd_resp_set_type(req, "application/octet-stream");
    httpd_resp_set_hdr(req, "X-Frame-Format", "RGB565");
    httpd_resp_set_hdr(req, "Cache-Control", "no-store");
    ret = httpd_resp_send(req, (const char *)frame.data, frame.length);

    esp_err_t release_ret = camera_capture_release_frame(&frame);
    if (release_ret != ESP_OK) {
        ESP_LOGE(TAG, "Failed to release frame: %s", esp_err_to_name(release_ret));
    }

    return ret;
}

static esp_err_t encode_frame_to_jpeg(const uint8_t *frame_data, uint32_t frame_length, uint32_t *out_size)
{
    esp_err_t ret = ensure_jpeg_encoder();
    if (ret != ESP_OK) {
        ESP_LOGE(TAG, "JPEG encoder not ready: %s", esp_err_to_name(ret));
        return ret;
    }

    jpeg_encode_cfg_t jpeg_cfg = {
        .height = CAMERA_STREAM_HEIGHT,
        .width = CAMERA_STREAM_WIDTH,
        .src_type = JPEG_ENCODE_IN_FORMAT_RGB565,
        .sub_sample = JPEG_DOWN_SAMPLING_YUV422,
        .image_quality = CAMERA_STREAM_JPEG_QUALITY,
    };

    return jpeg_encoder_process(s_jpeg_encoder,
                                &jpeg_cfg,
                                (uint8_t *)frame_data,
                                frame_length,
                                s_jpeg_output_buffer,
                                s_jpeg_output_buffer_size,
                                out_size);
}

static esp_err_t capture_jpg_handler(httpd_req_t *req)
{
    camera_frame_t frame = {0};
    esp_err_t ret = camera_capture_get_frame(&frame);
    if (ret != ESP_OK) {
        ESP_LOGE(TAG, "Failed to capture frame for JPEG: %s", esp_err_to_name(ret));
        httpd_resp_send_err(req, HTTPD_500_INTERNAL_SERVER_ERROR, "camera capture failed");
        return ret;
    }

    uint32_t out_size = 0;
    ret = encode_frame_to_jpeg(frame.data, frame.length, &out_size);
    if (ret != ESP_OK) {
        ESP_LOGE(TAG, "JPEG encode failed: %s", esp_err_to_name(ret));
        httpd_resp_send_err(req, HTTPD_500_INTERNAL_SERVER_ERROR, "jpeg encode failed");
        (void)camera_capture_release_frame(&frame);
        return ret;
    }

    httpd_resp_set_type(req, "image/jpeg");
    httpd_resp_set_hdr(req, "Cache-Control", "no-store");
    ret = httpd_resp_send(req, (const char *)s_jpeg_output_buffer, out_size);

    esp_err_t release_ret = camera_capture_release_frame(&frame);
    if (release_ret != ESP_OK) {
        ESP_LOGE(TAG, "Failed to release frame: %s", esp_err_to_name(release_ret));
    }

    return ret;
}


static esp_err_t stream_mjpg_handler(httpd_req_t *req)
{
    static const char *BOUNDARY = "--esp32p4frame\r\n";
    static const char *STREAM_TYPE = "multipart/x-mixed-replace;boundary=esp32p4frame";

    httpd_resp_set_type(req, STREAM_TYPE);
    httpd_resp_set_hdr(req, "Cache-Control", "no-store");

    while (true) {
        camera_frame_t frame = {0};
        esp_err_t ret = camera_capture_get_frame(&frame);
        if (ret != ESP_OK) {
            ESP_LOGE(TAG, "Failed to capture MJPEG frame: %s", esp_err_to_name(ret));
            return ret;
        }

        uint32_t out_size = 0;
        ret = encode_frame_to_jpeg(frame.data, frame.length, &out_size);
        esp_err_t release_ret = camera_capture_release_frame(&frame);
        if (release_ret != ESP_OK) {
            ESP_LOGE(TAG, "Failed to release MJPEG frame: %s", esp_err_to_name(release_ret));
        }

        if (ret != ESP_OK) {
            ESP_LOGE(TAG, "MJPEG encode failed: %s", esp_err_to_name(ret));
            return ret;
        }

        char header[96];
        int header_len = snprintf(header,
                                  sizeof(header),
                                  "Content-Type: image/jpeg\r\nContent-Length: %lu\r\n\r\n",
                                  (unsigned long)out_size);
        if (header_len <= 0 || header_len >= (int)sizeof(header)) {
            return ESP_FAIL;
        }

        if (httpd_resp_send_chunk(req, BOUNDARY, HTTPD_RESP_USE_STRLEN) != ESP_OK ||
            httpd_resp_send_chunk(req, header, header_len) != ESP_OK ||
            httpd_resp_send_chunk(req, (const char *)s_jpeg_output_buffer, out_size) != ESP_OK ||
            httpd_resp_send_chunk(req, "\r\n", 2) != ESP_OK) {
            ESP_LOGD(TAG, "MJPEG client disconnected");
            return ESP_OK;
        }
    }
}

static esp_err_t thermal_frame_handler(httpd_req_t *req)
{
    thermal_frame_t f;
    esp_err_t err = thermal_task_get_latest(&f);
    if (err == ESP_ERR_NOT_FOUND) {
        httpd_resp_set_type(req, "application/json");
        httpd_resp_set_hdr(req, "Cache-Control", "no-store");
        const char *body = "{\"event\":\"warming_up\"}";
        return httpd_resp_send(req, body, HTTPD_RESP_USE_STRLEN);
    }
    if (err != ESP_OK) {
        httpd_resp_send_err(req, HTTPD_500_INTERNAL_SERVER_ERROR, "thermal unavailable");
        return err;
    }

    httpd_resp_set_type(req, "application/json");
    httpd_resp_set_hdr(req, "Cache-Control", "no-store");

    char head[48];
    int hlen = snprintf(head, sizeof(head),
                        "{\"ts\":%lu,\"temps_c\":[",
                        (unsigned long)f.ts_ms);
    if (hlen < 0 || hlen >= (int)sizeof(head)) return ESP_FAIL;
    if (httpd_resp_send_chunk(req, head, hlen) != ESP_OK) return ESP_FAIL;

    char chunk[1024];
    int chunk_len = 0;
    for (int i = 0; i < MLX_PIXELS; ++i) {
        const float v = f.temps_c[i];
        const float safe = isfinite(v) ? v : 0.0f;
        const char *fmt = (i == MLX_PIXELS - 1) ? "%.2f" : "%.2f,";

        int wrote = snprintf(chunk + chunk_len,
                             sizeof(chunk) - chunk_len,
                             fmt, (double)safe);
        if (wrote < 0 || wrote >= (int)(sizeof(chunk) - chunk_len)) {
            if (chunk_len > 0) {
                if (httpd_resp_send_chunk(req, chunk, chunk_len) != ESP_OK) return ESP_FAIL;
                chunk_len = 0;
            }
            wrote = snprintf(chunk, sizeof(chunk), fmt, (double)safe);
            if (wrote < 0 || wrote >= (int)sizeof(chunk)) return ESP_FAIL;
        }
        chunk_len += wrote;
    }
    if (chunk_len > 0) {
        if (httpd_resp_send_chunk(req, chunk, chunk_len) != ESP_OK) return ESP_FAIL;
    }

    if (httpd_resp_send_chunk(req, "]}", 2) != ESP_OK) return ESP_FAIL;
    return httpd_resp_send_chunk(req, NULL, 0);  /* end of chunked response */
}

static bool query_float(const char *query, const char *key, float *out)
{
    char value[24];
    if (httpd_query_key_value(query, key, value, sizeof(value)) != ESP_OK) {
        return false;
    }

    char *end = NULL;
    const float parsed = strtof(value, &end);
    if (end == value) {
        return false;
    }

    *out = parsed;
    return true;
}

static bool query_u32(const char *query, const char *key, uint32_t *out)
{
    char value[24];
    if (httpd_query_key_value(query, key, value, sizeof(value)) != ESP_OK) {
        return false;
    }

    char *end = NULL;
    const unsigned long parsed = strtoul(value, &end, 10);
    if (end == value) {
        return false;
    }

    *out = (uint32_t)parsed;
    return true;
}

static esp_err_t control_manual_handler(httpd_req_t *req)
{
    char query[128] = {0};
    if (httpd_req_get_url_query_str(req, query, sizeof(query)) != ESP_OK) {
        httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, "missing query");
        return ESP_ERR_INVALID_ARG;
    }

    motor_control_manual_cmd_t cmd = {
        .ttl_ms = 300,
    };
    if (!query_float(query, "x", &cmd.x) ||
        !query_float(query, "y", &cmd.y) ||
        !query_float(query, "r", &cmd.r)) {
        httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, "missing x, y, or r");
        return ESP_ERR_INVALID_ARG;
    }
    (void)query_u32(query, "ttl", &cmd.ttl_ms);

    esp_err_t ret = motor_control_set_manual(&cmd);
    if (ret != ESP_OK) {
        httpd_resp_send_err(req, HTTPD_500_INTERNAL_SERVER_ERROR, "manual command failed");
        return ret;
    }

    httpd_resp_set_type(req, "application/json");
    httpd_resp_set_hdr(req, "Cache-Control", "no-store");
    return httpd_resp_send(req, "{\"ok\":true}", HTTPD_RESP_USE_STRLEN);
}

static esp_err_t control_stop_handler(httpd_req_t *req)
{
    motor_control_stop();
    httpd_resp_set_type(req, "application/json");
    httpd_resp_set_hdr(req, "Cache-Control", "no-store");
    return httpd_resp_send(req, "{\"ok\":true}", HTTPD_RESP_USE_STRLEN);
}

static esp_err_t control_status_handler(httpd_req_t *req)
{
    motor_control_status_t st = {0};
    motor_control_get_status(&st);

    char body[512];
    const int len = snprintf(body,
                             sizeof(body),
                             "{\"active\":%s,\"age_ms\":%lu,"
                             "\"x\":%.3f,\"y\":%.3f,\"r\":%.3f,"
                             "\"wheels\":{\"fl\":%.3f,\"fr\":%.3f,\"bl\":%.3f,\"br\":%.3f},"
                             "\"duties\":{\"fl\":%lu,\"fr\":%lu,\"bl\":%lu,\"br\":%lu},"
                             "\"encoders\":{\"fl\":%lld,\"fr\":%lld,\"bl\":%lld,\"br\":%lld}}",
                             st.active ? "true" : "false",
                             (unsigned long)st.age_ms,
                             (double)st.x,
                             (double)st.y,
                             (double)st.r,
                             (double)st.wheel_fl,
                             (double)st.wheel_fr,
                             (double)st.wheel_bl,
                             (double)st.wheel_br,
                             (unsigned long)st.duty_fl,
                             (unsigned long)st.duty_fr,
                             (unsigned long)st.duty_bl,
                             (unsigned long)st.duty_br,
                             (long long)st.enc_fl,
                             (long long)st.enc_fr,
                             (long long)st.enc_bl,
                             (long long)st.enc_br);
    if (len <= 0 || len >= (int)sizeof(body)) {
        return ESP_FAIL;
    }

    httpd_resp_set_type(req, "application/json");
    httpd_resp_set_hdr(req, "Cache-Control", "no-store");
    return httpd_resp_send(req, body, len);
}

esp_err_t http_camera_server_start(void)
{
    httpd_config_t config = HTTPD_DEFAULT_CONFIG();
    config.server_port = 80;
    /* thermal_frame_handler keeps a 3 KB thermal_frame_t on the stack
     * plus a 1 KB JSON chunk buffer; the 4 KB default overflows. */
    config.stack_size = 8192;

    httpd_handle_t server = NULL;
    esp_err_t ret = httpd_start(&server, &config);
    if (ret != ESP_OK) {
        ESP_LOGE(TAG, "Failed to start HTTP server: %s", esp_err_to_name(ret));
        return ret;
    }

    httpd_config_t stream_config = HTTPD_DEFAULT_CONFIG();
    stream_config.server_port = 81;
    stream_config.ctrl_port = config.ctrl_port + 1;
    stream_config.stack_size = 8192;

    httpd_handle_t stream_server = NULL;
    ret = httpd_start(&stream_server, &stream_config);
    if (ret != ESP_OK) {
        ESP_LOGE(TAG, "Failed to start stream HTTP server: %s", esp_err_to_name(ret));
        httpd_stop(server);
        return ret;
    }

    const httpd_uri_t root_uri = {
        .uri = "/",
        .method = HTTP_GET,
        .handler = root_handler,
    };
    const httpd_uri_t thermal_uri = {
        .uri = "/thermal",
        .method = HTTP_GET,
        .handler = root_handler,
    };
    const httpd_uri_t capture_raw_uri = {
        .uri = "/capture/visible.raw",
        .method = HTTP_GET,
        .handler = capture_raw_handler,
    };
    const httpd_uri_t capture_jpg_uri = {
        .uri = "/capture/visible.jpg",
        .method = HTTP_GET,
        .handler = capture_jpg_handler,
    };
    const httpd_uri_t stream_mjpg_uri = {
        .uri = "/stream.mjpg",
        .method = HTTP_GET,
        .handler = stream_mjpg_handler,
    };
    const httpd_uri_t thermal_frame_uri = {
        .uri = "/thermal/frame",
        .method = HTTP_GET,
        .handler = thermal_frame_handler,
    };
    const httpd_uri_t control_manual_uri = {
        .uri = "/control/manual",
        .method = HTTP_GET,
        .handler = control_manual_handler,
    };
    const httpd_uri_t control_stop_uri = {
        .uri = "/control/stop",
        .method = HTTP_GET,
        .handler = control_stop_handler,
    };
    const httpd_uri_t control_status_uri = {
        .uri = "/control/status",
        .method = HTTP_GET,
        .handler = control_status_handler,
    };

    ESP_RETURN_ON_ERROR(httpd_register_uri_handler(server, &root_uri), TAG, "Failed to register /");
    ESP_RETURN_ON_ERROR(httpd_register_uri_handler(server, &thermal_uri), TAG, "Failed to register /thermal");
    ESP_RETURN_ON_ERROR(httpd_register_uri_handler(server, &capture_raw_uri), TAG, "Failed to register raw capture");
    ESP_RETURN_ON_ERROR(httpd_register_uri_handler(server, &capture_jpg_uri), TAG, "Failed to register jpg capture");
    ESP_RETURN_ON_ERROR(httpd_register_uri_handler(stream_server, &stream_mjpg_uri), TAG, "Failed to register MJPEG stream");
    ESP_RETURN_ON_ERROR(httpd_register_uri_handler(server, &thermal_frame_uri), TAG, "Failed to register /thermal/frame");
    ESP_RETURN_ON_ERROR(httpd_register_uri_handler(server, &control_manual_uri), TAG, "Failed to register /control/manual");
    ESP_RETURN_ON_ERROR(httpd_register_uri_handler(server, &control_stop_uri), TAG, "Failed to register /control/stop");
    ESP_RETURN_ON_ERROR(httpd_register_uri_handler(server, &control_status_uri), TAG, "Failed to register /control/status");

    ESP_LOGD(TAG, "HTTP camera server started on port %d, stream port %d",
             config.server_port,
             stream_config.server_port);
    return ESP_OK;
}
