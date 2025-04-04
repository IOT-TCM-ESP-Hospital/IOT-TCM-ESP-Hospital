/*
 * Network Command Task
 *
 * Implement the command processing module for use when either the
 * Ethernet or WiFi interfaces are active.  Enable mDNS for device
 * discovery.
 *
 * Copyright 2020-2022 Dan Julio
 *
 * This file is part of tCam.
 *
 * tCam is free software: you can redistribute it and/or modify
 * it under the terms of the GNU General Public License as published by
 * the Free Software Foundation, either version 3 of the License, or
 * (at your option) any later version.
 *
 * tCam is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU General Public License for more details.
 *
 * You should have received a copy of the GNU General Public License
 * along with tCam.  If not, see <https://www.gnu.org/licenses/>.
 *
 */
#include "net_cmd_task.h"
#include "ctrl_task.h"
#include "cmd_utilities.h"
#include "net_utilities.h"
#include "system_config.h"
#include "esp_system.h"
#include "esp_log.h"
#include "esp_ota_ops.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "lwip/err.h"
#include "lwip/sockets.h"
#include "lwip/sys.h"
#include <lwip/netdb.h>
#include "mdns.h"
#include "esp_event.h"
#include "esp_websocket_client.h"

#define USE_WEBSOCKET_ONLY

static const char *TAG = "ws_client";
static esp_websocket_client_handle_t client = NULL;

/* WebSocket event handler - routes received messages to the existing command processing flow */
static void websocket_event_handler(void *handler_args, esp_event_base_t base, int32_t event_id, void *event_data)
{
	esp_websocket_event_data_t *data = (esp_websocket_event_data_t *)event_data;

	switch (event_id)
	{
	case WEBSOCKET_EVENT_CONNECTED:
		ESP_LOGI(TAG, "WebSocket connected");
		break;
	case WEBSOCKET_EVENT_DISCONNECTED:
		ESP_LOGI(TAG, "WebSocket disconnected");
		break;
	case WEBSOCKET_EVENT_DATA:
		ESP_LOGI(TAG, "WebSocket received data: %.*s", data->data_len, (char *)data->data_ptr);
		// Pass the received data to the existing TCP command processing logic
		push_rx_data((char *)data->data_ptr, data->data_len);
		while (process_rx_data())
		{
			// Process all available commands
		}
		break;
	default:
		break;
	}
}

/*
 * mDNS TXT records and keys
 */
#define NUM_SERVICE_TXT_ITEMS 3
static mdns_txt_item_t service_txt_data[NUM_SERVICE_TXT_ITEMS];
static char *txt_item_keys[NUM_SERVICE_TXT_ITEMS] = {
	"model",
	"interface",
	"version"};

/* Forward declaration */
static void net_cmd_start_mdns();

/*
 * Network CMD Task API
 */
void net_cmd_task()
{
	// Initialize and start the WebSocket client to connect to AWS
	esp_websocket_client_config_t websocket_cfg = {
		.uri = "ws://your-aws-endpoint.com/ws", // Use wss:// if SSL/TLS is enabled
	};

	client = esp_websocket_client_init(&websocket_cfg);
	esp_websocket_register_events(client, WEBSOCKET_EVENT_ANY, websocket_event_handler, NULL);
	esp_websocket_client_start(client);

	// Wait until the network interface is connected
	if (!(*net_is_connected)())
	{
		vTaskDelay(pdMS_TO_TICKS(500));
	}

	// Start the mDNS service (if needed)
	net_cmd_start_mdns();

#ifdef USE_WEBSOCKET_ONLY
	// In WebSocket-only mode, bypass the TCP server.
	// Optionally, you could add reconnection or heartbeat logic here.
	while (1)
	{
		// The WebSocket event handler processes incoming commands.
		// Here we just wait.
		vTaskDelay(pdMS_TO_TICKS(100));
	}
#else
	// ----------------------------
	// Original TCP Server Code
	// ----------------------------
	char rx_buffer[256];
	char addr_str[16];
	int err;
	int flag;
	int len;
	int listen_sock;
	struct sockaddr_in destAddr;
	struct sockaddr_in sourceAddr;
	uint32_t addrLen;

	ESP_LOGI(TAG, "Starting TCP server");
	// Config IPV4
	destAddr.sin_addr.s_addr = htonl(INADDR_ANY);
	destAddr.sin_family = AF_INET;
	destAddr.sin_port = htons(CMD_PORT);
	inet_ntoa_r(destAddr.sin_addr, addr_str, sizeof(addr_str) - 1);

	// socket - bind - listen - accept
	listen_sock = socket(AF_INET, SOCK_STREAM, IPPROTO_IP);
	if (listen_sock < 0)
	{
		ESP_LOGE(TAG, "Unable to create socket: errno %d", errno);
		goto error;
	}
	ESP_LOGI(TAG, "Socket created");

	flag = 1;
	setsockopt(listen_sock, SOL_SOCKET, SO_REUSEADDR, &flag, sizeof(flag));
	err = bind(listen_sock, (struct sockaddr *)&destAddr, sizeof(destAddr));
	if (err != 0)
	{
		ESP_LOGE(TAG, "Socket unable to bind: errno %d", errno);
		goto error;
	}
	ESP_LOGI(TAG, "Socket bound");

	while (1)
	{
		init_command_processor();

		err = listen(listen_sock, 1);
		if (err != 0)
		{
			ESP_LOGE(TAG, "Error occurred during listen: errno %d", errno);
			break;
		}
		ESP_LOGI(TAG, "Socket listening");

		addrLen = sizeof(sourceAddr);
		int client_sock = accept(listen_sock, (struct sockaddr *)&sourceAddr, &addrLen);
		if (client_sock < 0)
		{
			ESP_LOGE(TAG, "Unable to accept connection: errno %d", errno);
			break;
		}
		ESP_LOGI(TAG, "Socket accepted");
		bool connected = true;

		// Handle communication with the connected client
		while (1)
		{
			len = recv(client_sock, rx_buffer, sizeof(rx_buffer), MSG_DONTWAIT);
			if (len < 0)
			{
				if ((errno == EAGAIN) || (errno == EWOULDBLOCK))
				{
					if ((*net_is_connected)())
					{
						vTaskDelay(pdMS_TO_TICKS(50));
					}
					else
					{
						ESP_LOGI(TAG, "Closing connection");
						break;
					}
				}
				else
				{
					ESP_LOGE(TAG, "recv failed: errno %d", errno);
					break;
				}
			}
			else if (len == 0)
			{
				ESP_LOGI(TAG, "Connection closed");
				break;
			}
			else
			{
				push_rx_data(rx_buffer, len);
				while (process_rx_data())
				{
					// Process all available commands
				}
			}
		}

		// Close client session and restart listening
		connected = false;
		ESP_LOGI(TAG, "Shutting down socket and restarting...");
		shutdown(client_sock, 0);
		close(client_sock);
	}

error:
	ESP_LOGI(TAG, "Serious networking error - bailing");
	ctrl_set_fault_type(CTRL_FAULT_NETWORK);
	vTaskDelete(NULL);
#endif // USE_WEBSOCKET_ONLY
}

/**
 * True when connected to a client (TCP mode)
 */
bool net_cmd_connected()
{
#ifdef USE_WEBSOCKET_ONLY
	// In WebSocket mode, you might implement your own connection status.
	return true;
#else
	// Return TCP connection status.
	extern bool connected; // assuming 'connected' is declared appropriately
	return connected;
#endif
}

/**
 * Return socket descriptor (TCP mode)
 */
int net_cmd_get_socket()
{
#ifdef USE_WEBSOCKET_ONLY
	// In WebSocket mode, this is not applicable.
	return -1;
#else
	extern int client_sock; // assuming 'client_sock' is declared appropriately
	return client_sock;
#endif
}

/*
 * mDNS service initialization
 */
static void net_cmd_start_mdns()
{
	char model_type[2];	 // Camera Model number "N"
	char txt_if_type[9]; // "WiFi" or "Ethernet"
	const esp_app_desc_t *app_desc;
	int brd_type;
	int if_type;
	esp_err_t ret;
	net_info_t *net_infoP;

	ret = mdns_init();
	if (ret != ESP_OK)
	{
		ESP_LOGE(TAG, "Could not initialize mDNS (%d)", ret);
		return;
	}

	net_infoP = net_get_info();
	ret = mdns_hostname_set(net_infoP->ap_ssid);
	if (ret != ESP_OK)
	{
		ESP_LOGE(TAG, "Could not set mDNS hostname %s (%d)", net_infoP->ap_ssid, ret);
		return;
	}

	app_desc = esp_ota_get_app_description();
	ctrl_get_if_mode(&brd_type, &if_type);
	model_type[0] = '0' + ((brd_type == CTRL_BRD_ETH_TYPE) ? CAMERA_MODEL_NUM_ETH : CAMERA_MODEL_NUM_WIFI);
	model_type[1] = 0;
	if (if_type == CTRL_IF_MODE_ETH)
	{
		strcpy(txt_if_type, "Ethernet");
	}
	else
	{
		strcpy(txt_if_type, "WiFi");
	}
	service_txt_data[0].key = txt_item_keys[0];
	service_txt_data[0].value = model_type;
	service_txt_data[1].key = txt_item_keys[1];
	service_txt_data[1].value = txt_if_type;
	service_txt_data[2].key = txt_item_keys[2];
	service_txt_data[2].value = app_desc->version;

	ret = mdns_service_add(NULL, "_tcam-socket", "_tcp", CMD_PORT, service_txt_data, NUM_SERVICE_TXT_ITEMS);
	if (ret != ESP_OK)
	{
		ESP_LOGE(TAG, "Could not initialize mDNS service (%d)", ret);
		return;
	}
	ESP_LOGI(TAG, "mDNS started");
}
