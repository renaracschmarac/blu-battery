package com.blubattery.monitor;

import android.Manifest;
import android.app.Activity;
import android.app.AlertDialog;
import android.bluetooth.BluetoothAdapter;
import android.bluetooth.BluetoothDevice;
import android.bluetooth.BluetoothGatt;
import android.bluetooth.BluetoothGattCallback;
import android.bluetooth.BluetoothGattCharacteristic;
import android.bluetooth.BluetoothGattDescriptor;
import android.bluetooth.BluetoothGattService;
import android.bluetooth.BluetoothManager;
import android.bluetooth.BluetoothProfile;
import android.bluetooth.le.BluetoothLeScanner;
import android.bluetooth.le.ScanCallback;
import android.bluetooth.le.ScanRecord;
import android.bluetooth.le.ScanResult;
import android.content.Context;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.os.ParcelUuid;
import android.util.Log;
import android.view.Gravity;
import android.view.View;
import android.view.WindowInsets;
import android.view.WindowInsetsController;
import android.view.WindowManager;
import android.view.ViewGroup;
import android.widget.Button;
import android.widget.EditText;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.TextView;
import android.widget.Toast;
import android.text.InputType;

import java.io.ByteArrayOutputStream;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.UUID;

public final class MainActivity extends Activity {
    private static final String TAG = "BluBattery";
    private static final int REQUEST_BLUETOOTH = 100;
    private static final int DEFAULT_POLL_INTERVAL_MS = 200;
    private static final String SETTINGS_NAME = "display_settings";
    private static final String KEY_AMPS_OUT = "amps_out";
    private static final String KEY_AMPS_IN = "amps_in";
    private static final String KEY_BATTERY_ADDRESS = "battery_address";
    private static final String KEY_BATTERY_LABEL = "battery_label";
    private static final float DEFAULT_AMPS_OUT = 100.0f;
    private static final float DEFAULT_AMPS_IN = 20.0f;
    private static final int OBSERVED_BMS_ADVERTISEMENT_ID = 0x0104;
    private static final int SCAN_SELECTION_DELAY_MS = 3000;
    private static final UUID SERVICE_UUID =
            UUID.fromString("0000fff0-0000-1000-8000-00805f9b34fb");
    private static final UUID NOTIFY_UUID =
            UUID.fromString("0000fff1-0000-1000-8000-00805f9b34fb");
    private static final UUID COMMAND_UUID =
            UUID.fromString("0000fff2-0000-1000-8000-00805f9b34fb");
    private static final UUID CCCD_UUID =
            UUID.fromString("00002902-0000-1000-8000-00805f9b34fb");
    private static final byte[] STATUS_REQUEST =
            new byte[] {(byte) 0xD2, 0x03, 0x00, 0x00, 0x00, 0x3E, (byte) 0xD7, (byte) 0xB9};

    private final Handler handler = new Handler(Looper.getMainLooper());
    private final ByteArrayOutputStream responseBuffer = new ByteArrayOutputStream();
    private SharedPreferences preferences;
    private MetricView view;
    private BluetoothAdapter adapter;
    private BluetoothLeScanner scanner;
    private BluetoothGatt gatt;
    private BluetoothGattCharacteristic commandCharacteristic;
    private final Map<String, DiscoveredBms> foundBms = new LinkedHashMap<>();
    private boolean scanning;
    private boolean tryingRememberedDevice;
    private boolean selectingDevice;
    private boolean suppressDisconnectScan;
    private int pollIntervalMs;
    private final Runnable resolveScanResults = this::chooseScannedDevice;

    private final Runnable requestStatus = new Runnable() {
        @Override
        public void run() {
            if (gatt != null && commandCharacteristic != null) {
                commandCharacteristic.setWriteType(BluetoothGattCharacteristic.WRITE_TYPE_NO_RESPONSE);
                commandCharacteristic.setValue(STATUS_REQUEST);
                if (!gatt.writeCharacteristic(commandCharacteristic)) {
                    Log.w(TAG, "telemetry request failed");
                    view.setStatus("Telemetry request failed");
                }
                handler.postDelayed(this, pollIntervalMs);
            }
        }
    };

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        pollIntervalMs = Math.max(50, Math.min(10000,
                getIntent().getIntExtra("poll_interval_ms", DEFAULT_POLL_INTERVAL_MS)));
        Log.i(TAG, "poll_interval_ms=" + pollIntervalMs);
        preferences = getSharedPreferences(SETTINGS_NAME, MODE_PRIVATE);
        float ampsOut = Math.abs(preferences.getFloat(KEY_AMPS_OUT, DEFAULT_AMPS_OUT));
        float ampsIn = Math.abs(preferences.getFloat(KEY_AMPS_IN, DEFAULT_AMPS_IN));
        Log.i(TAG, String.format(Locale.US,
                "current_scale out=-%.1fA in=+%.1fA", ampsOut, ampsIn));
        view = new MetricView(this, ampsOut, ampsIn);
        setContentView(createContentView());
        hideSystemUi();
        startWhenPermitted();
    }

    private View createContentView() {
        FrameLayout root = new FrameLayout(this);
        root.addView(view, new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));

        Button settings = new Button(this);
        settings.setText("SETTINGS");
        settings.setTextColor(Color.WHITE);
        settings.setOnClickListener(ignored -> showCurrentSettings());
        FrameLayout.LayoutParams params = new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT,
                Gravity.TOP | Gravity.END);
        int margin = dp(12);
        params.setMargins(margin, margin, margin, margin);
        root.addView(settings, params);
        return root;
    }

    private int dp(int value) {
        return Math.round(value * getResources().getDisplayMetrics().density);
    }

    private void showCurrentSettings() {
        LinearLayout fields = new LinearLayout(this);
        fields.setOrientation(LinearLayout.VERTICAL);
        int padding = dp(20);
        fields.setPadding(padding, dp(8), padding, 0);

        EditText ampsOut = currentField("Amps OUT (-)", view.getAmpsOut());
        EditText ampsIn = currentField("Amps IN (+)", view.getAmpsIn());
        fields.addView(labeledField("Bright red at Amps OUT (-)", ampsOut));
        fields.addView(labeledField("Bright red at Amps IN (+)", ampsIn));

        AlertDialog dialog = new AlertDialog.Builder(this)
                .setTitle("Current Color Scale")
                .setMessage("The Current band is green at 0 A, yellow at half scale, and red at either limit.")
                .setView(fields)
                .setNegativeButton("Cancel", null)
                .setNeutralButton("Re-scan for battery", null)
                .setPositiveButton("Save", null)
                .create();
        dialog.setOnShowListener(ignored -> {
            dialog.getButton(AlertDialog.BUTTON_NEUTRAL).setOnClickListener(button -> {
                dialog.dismiss();
                rescanForBattery();
            });
            dialog.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener(button -> {
                    try {
                        float out = Float.parseFloat(ampsOut.getText().toString().trim());
                        float in = Float.parseFloat(ampsIn.getText().toString().trim());
                        if (out <= 0.0f || in <= 0.0f) {
                            throw new NumberFormatException();
                        }
                        preferences.edit()
                                .putFloat(KEY_AMPS_OUT, out)
                                .putFloat(KEY_AMPS_IN, in)
                                .apply();
                        view.setCurrentScale(out, in);
                        Log.i(TAG, String.format(Locale.US,
                                "current_scale out=-%.1fA in=+%.1fA", out, in));
                        dialog.dismiss();
                    } catch (NumberFormatException error) {
                        Toast.makeText(this,
                                "Enter positive magnitudes for OUT and IN.",
                                Toast.LENGTH_SHORT).show();
                    }
                });
        });
        dialog.show();
    }

    private EditText currentField(String hint, float value) {
        EditText input = new EditText(this);
        input.setHint(hint);
        input.setText(String.format(Locale.US, "%.1f", value));
        input.setSelectAllOnFocus(true);
        input.setInputType(InputType.TYPE_CLASS_NUMBER | InputType.TYPE_NUMBER_FLAG_DECIMAL);
        return input;
    }

    private View labeledField(String label, EditText input) {
        LinearLayout group = new LinearLayout(this);
        group.setOrientation(LinearLayout.VERTICAL);
        TextView text = new TextView(this);
        text.setText(label);
        group.addView(text);
        group.addView(input);
        return group;
    }

    @Override
    protected void onDestroy() {
        handler.removeCallbacks(requestStatus);
        handler.removeCallbacks(resolveScanResults);
        stopScan();
        if (gatt != null) {
            suppressDisconnectScan = true;
            gatt.disconnect();
            gatt.close();
            gatt = null;
        }
        super.onDestroy();
    }

    @Override
    public void onRequestPermissionsResult(int requestCode, String[] permissions, int[] grantResults) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults);
        if (requestCode == REQUEST_BLUETOOTH && allGranted(grantResults)) {
            connectRememberedOrScan();
        } else if (requestCode == REQUEST_BLUETOOTH) {
            view.setStatus("Bluetooth permission required");
        }
    }

    private void startWhenPermitted() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            if (checkSelfPermission(Manifest.permission.BLUETOOTH_SCAN) != PackageManager.PERMISSION_GRANTED
                    || checkSelfPermission(Manifest.permission.BLUETOOTH_CONNECT) != PackageManager.PERMISSION_GRANTED) {
                requestPermissions(
                        new String[] {Manifest.permission.BLUETOOTH_SCAN, Manifest.permission.BLUETOOTH_CONNECT},
                        REQUEST_BLUETOOTH);
                return;
            }
        } else if (checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(new String[] {Manifest.permission.ACCESS_FINE_LOCATION}, REQUEST_BLUETOOTH);
            return;
        }
        connectRememberedOrScan();
    }

    @SuppressWarnings("MissingPermission")
    private void connectRememberedOrScan() {
        BluetoothManager manager = (BluetoothManager) getSystemService(Context.BLUETOOTH_SERVICE);
        adapter = manager.getAdapter();
        if (adapter == null || !adapter.isEnabled()) {
            view.setStatus("Turn Bluetooth on");
            return;
        }
        String savedAddress = preferences.getString(KEY_BATTERY_ADDRESS, null);
        if (savedAddress != null) {
            try {
                tryingRememberedDevice = true;
                BluetoothDevice saved = adapter.getRemoteDevice(savedAddress);
                String savedLabel = preferences.getString(KEY_BATTERY_LABEL, savedAddress);
                view.setStatus("Connecting to " + savedLabel);
                Log.i(TAG, "connecting_saved address=" + savedAddress);
                connectDevice(saved);
                return;
            } catch (IllegalArgumentException error) {
                preferences.edit().remove(KEY_BATTERY_ADDRESS).remove(KEY_BATTERY_LABEL).apply();
            }
        }
        beginScan();
    }

    @SuppressWarnings("MissingPermission")
    private void beginScan() {
        BluetoothManager manager = (BluetoothManager) getSystemService(Context.BLUETOOTH_SERVICE);
        adapter = manager.getAdapter();
        if (adapter == null || !adapter.isEnabled()) {
            view.setStatus("Turn Bluetooth on");
            return;
        }
        scanner = adapter.getBluetoothLeScanner();
        if (scanner == null) {
            view.setStatus("BLE scanner unavailable");
            return;
        }
        foundBms.clear();
        selectingDevice = false;
        handler.removeCallbacks(resolveScanResults);
        view.setStatus("Scanning for BMS");
        scanning = true;
        scanner.startScan(scanCallback);
    }

    @SuppressWarnings("MissingPermission")
    private void stopScan() {
        if (scanning && scanner != null) {
            scanner.stopScan(scanCallback);
        }
        scanning = false;
    }

    @SuppressWarnings("MissingPermission")
    private void rescanForBattery() {
        handler.removeCallbacks(requestStatus);
        handler.removeCallbacks(resolveScanResults);
        stopScan();
        tryingRememberedDevice = false;
        preferences.edit().remove(KEY_BATTERY_ADDRESS).remove(KEY_BATTERY_LABEL).apply();
        if (gatt != null) {
            gatt.disconnect();
            gatt.close();
            gatt = null;
        }
        commandCharacteristic = null;
        beginScan();
    }

    @SuppressWarnings("MissingPermission")
    private void connectDevice(BluetoothDevice device) {
        stopScan();
        selectingDevice = false;
        view.setStatus("Connecting to BMS");
        gatt = device.connectGatt(MainActivity.this, false, gattCallback, BluetoothDevice.TRANSPORT_LE);
    }

    private final ScanCallback scanCallback = new ScanCallback() {
        @Override
        @SuppressWarnings("MissingPermission")
        public void onScanResult(int callbackType, ScanResult result) {
            if (!isBmsCandidate(result)) {
                return;
            }
            BluetoothDevice device = result.getDevice();
            String name = advertisedName(result);
            if (!foundBms.containsKey(device.getAddress())) {
                foundBms.put(device.getAddress(), new DiscoveredBms(device, name, result.getRssi()));
                Log.i(TAG, "scan_candidate address=" + device.getAddress() + " name=" + name);
                view.setStatus("Found " + foundBms.size() + " BMS candidate(s)");
                handler.removeCallbacks(resolveScanResults);
                handler.postDelayed(resolveScanResults, SCAN_SELECTION_DELAY_MS);
            }
        }

        @Override
        public void onScanFailed(int errorCode) {
            view.setStatus("Scan error " + errorCode);
        }
    };

    private boolean isBmsCandidate(ScanResult result) {
        ScanRecord record = result.getScanRecord();
        if (record == null) {
            return false;
        }
        List<ParcelUuid> services = record.getServiceUuids();
        if (services != null && services.contains(new ParcelUuid(SERVICE_UUID))) {
            return true;
        }
        return record.getManufacturerSpecificData(OBSERVED_BMS_ADVERTISEMENT_ID) != null;
    }

    @SuppressWarnings("MissingPermission")
    private String advertisedName(ScanResult result) {
        String name = result.getScanRecord() == null ? null : result.getScanRecord().getDeviceName();
        if (name == null) {
            name = result.getDevice().getName();
        }
        return name == null ? "Unnamed BMS" : name;
    }

    private void chooseScannedDevice() {
        if (foundBms.isEmpty() || selectingDevice) {
            return;
        }
        if (foundBms.size() == 1) {
            connectDevice(foundBms.values().iterator().next().device);
            return;
        }
        selectingDevice = true;
        stopScan();
        List<DiscoveredBms> candidates = new ArrayList<>(foundBms.values());
        String[] labels = new String[candidates.size()];
        for (int index = 0; index < candidates.size(); index++) {
            labels[index] = candidates.get(index).label();
        }
        new AlertDialog.Builder(this)
                .setTitle("Select Battery BMS")
                .setItems(labels, (dialog, which) -> connectDevice(candidates.get(which).device))
                .setNegativeButton("Cancel", (dialog, which) -> {
                    selectingDevice = false;
                    beginScan();
                })
                .show();
    }

    private final BluetoothGattCallback gattCallback = new BluetoothGattCallback() {
        @Override
        @SuppressWarnings("MissingPermission")
        public void onConnectionStateChange(BluetoothGatt bluetoothGatt, int status, int newState) {
            if (status == BluetoothGatt.GATT_SUCCESS && newState == BluetoothProfile.STATE_CONNECTED) {
                Log.i(TAG, "connected");
                view.setStatus("Connected");
                bluetoothGatt.discoverServices();
            } else if (newState == BluetoothProfile.STATE_DISCONNECTED) {
                Log.i(TAG, "disconnected status=" + status);
                handler.removeCallbacks(requestStatus);
                commandCharacteristic = null;
                bluetoothGatt.close();
                gatt = null;
                if (suppressDisconnectScan) {
                    suppressDisconnectScan = false;
                    return;
                }
                if (tryingRememberedDevice) {
                    tryingRememberedDevice = false;
                    Log.i(TAG, "saved connection unavailable; scanning");
                }
                view.setStatus("Disconnected - searching");
                handler.postDelayed(MainActivity.this::beginScan, 1000);
            }
        }

        @Override
        @SuppressWarnings("MissingPermission")
        public void onServicesDiscovered(BluetoothGatt bluetoothGatt, int status) {
            if (status != BluetoothGatt.GATT_SUCCESS) {
                rejectCandidate(bluetoothGatt, "Service discovery failed");
                return;
            }
            BluetoothGattService service = bluetoothGatt.getService(SERVICE_UUID);
            if (service == null) {
                rejectCandidate(bluetoothGatt, "Candidate is not a compatible BMS");
                return;
            }
            BluetoothGattCharacteristic notify = service.getCharacteristic(NOTIFY_UUID);
            commandCharacteristic = service.getCharacteristic(COMMAND_UUID);
            BluetoothGattDescriptor cccd = notify == null ? null : notify.getDescriptor(CCCD_UUID);
            if (notify == null || commandCharacteristic == null || cccd == null) {
                rejectCandidate(bluetoothGatt, "Candidate is not a compatible BMS");
                return;
            }
            rememberBattery(bluetoothGatt.getDevice());
            tryingRememberedDevice = false;
            bluetoothGatt.setCharacteristicNotification(notify, true);
            cccd.setValue(BluetoothGattDescriptor.ENABLE_NOTIFICATION_VALUE);
            bluetoothGatt.writeDescriptor(cccd);
        }

        @Override
        public void onDescriptorWrite(BluetoothGatt bluetoothGatt, BluetoothGattDescriptor descriptor, int status) {
            if (descriptor.getUuid().equals(CCCD_UUID) && status == BluetoothGatt.GATT_SUCCESS) {
                view.setStatus(String.format(Locale.US, "Live %.1f Hz", 1000.0 / pollIntervalMs));
                handler.removeCallbacks(requestStatus);
                handler.post(requestStatus);
            } else {
                view.setStatus("Notification setup failed");
            }
        }

        @Override
        public void onCharacteristicChanged(BluetoothGatt bluetoothGatt, BluetoothGattCharacteristic characteristic) {
            if (characteristic.getUuid().equals(NOTIFY_UUID)) {
                acceptChunk(characteristic.getValue());
            }
        }
    };

    @SuppressWarnings("MissingPermission")
    private void rememberBattery(BluetoothDevice device) {
        DiscoveredBms candidate = foundBms.get(device.getAddress());
        String label = candidate == null ? device.getName() : candidate.name;
        if (label == null) {
            label = "Battery BMS";
        }
        preferences.edit()
                .putString(KEY_BATTERY_ADDRESS, device.getAddress())
                .putString(KEY_BATTERY_LABEL, label)
                .apply();
        Log.i(TAG, "remembered_bms address=" + device.getAddress() + " name=" + label);
    }

    @SuppressWarnings("MissingPermission")
    private void rejectCandidate(BluetoothGatt bluetoothGatt, String status) {
        Log.i(TAG, "rejected_candidate address=" + bluetoothGatt.getDevice().getAddress());
        if (tryingRememberedDevice) {
            preferences.edit().remove(KEY_BATTERY_ADDRESS).remove(KEY_BATTERY_LABEL).apply();
            tryingRememberedDevice = false;
        }
        suppressDisconnectScan = true;
        bluetoothGatt.disconnect();
        bluetoothGatt.close();
        gatt = null;
        commandCharacteristic = null;
        view.setStatus(status + " - scanning");
        handler.postDelayed(MainActivity.this::beginScan, 1000);
    }

    private void acceptChunk(byte[] chunk) {
        responseBuffer.write(chunk, 0, chunk.length);
        byte[] data = responseBuffer.toByteArray();
        int start = findStart(data);
        if (start < 0) {
            responseBuffer.reset();
            return;
        }
        if (data.length - start < 3) {
            return;
        }
        int size = 3 + (data[start + 2] & 0xFF) + 2;
        if (data.length - start < size) {
            return;
        }
        byte[] frame = new byte[size];
        System.arraycopy(data, start, frame, 0, size);
        responseBuffer.reset();
        if (!validStatusFrame(frame)) {
            view.setStatus("Invalid response");
            return;
        }
        double voltage = unsigned16(frame, 83) * 0.1;
        double current = (unsigned16(frame, 85) - 30000) * 0.1;
        double remaining = unsigned16(frame, 99) * 0.1;
        Log.i(TAG, String.format(Locale.US,
                "telemetry voltage=%.1fV current=%.1fA remaining=%.1fAh",
                voltage, current, remaining));
        view.setMetrics(voltage, current, remaining);
    }

    private static boolean validStatusFrame(byte[] frame) {
        if (frame.length < 101 || (frame[0] & 0xFF) != 0xD2 || (frame[1] & 0xFF) != 0x03) {
            return false;
        }
        int expected = crc16(frame, frame.length - 2);
        int actual = (frame[frame.length - 2] & 0xFF) | ((frame[frame.length - 1] & 0xFF) << 8);
        return expected == actual;
    }

    private static int findStart(byte[] data) {
        for (int i = 0; i < data.length; i++) {
            if ((data[i] & 0xFF) == 0xD2) {
                return i;
            }
        }
        return -1;
    }

    private static int unsigned16(byte[] value, int offset) {
        return ((value[offset] & 0xFF) << 8) | (value[offset + 1] & 0xFF);
    }

    private static int crc16(byte[] value, int length) {
        int checksum = 0xFFFF;
        for (int i = 0; i < length; i++) {
            checksum ^= value[i] & 0xFF;
            for (int bit = 0; bit < 8; bit++) {
                checksum = (checksum & 1) != 0 ? (checksum >> 1) ^ 0xA001 : checksum >> 1;
            }
        }
        return checksum;
    }

    private boolean allGranted(int[] results) {
        if (results.length == 0) {
            return false;
        }
        for (int result : results) {
            if (result != PackageManager.PERMISSION_GRANTED) {
                return false;
            }
        }
        return true;
    }

    private void hideSystemUi() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            WindowInsetsController controller = getWindow().getInsetsController();
            if (controller != null) {
                controller.hide(WindowInsets.Type.systemBars());
                controller.setSystemBarsBehavior(
                        WindowInsetsController.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE);
            }
        } else {
            getWindow().getDecorView().setSystemUiVisibility(
                    View.SYSTEM_UI_FLAG_FULLSCREEN
                            | View.SYSTEM_UI_FLAG_HIDE_NAVIGATION
                            | View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY);
        }
    }

    private static final class DiscoveredBms {
        private final BluetoothDevice device;
        private final String name;
        private final int rssi;

        DiscoveredBms(BluetoothDevice device, String name, int rssi) {
            this.device = device;
            this.name = name;
            this.rssi = rssi;
        }

        String label() {
            return String.format(Locale.US, "%s  %s  (%d dBm)", name, device.getAddress(), rssi);
        }
    }

    private static final class MetricView extends View {
        private static final int ZERO_CURRENT_COLOR = Color.rgb(10, 52, 48);
        private static final int MID_CURRENT_COLOR = Color.rgb(246, 190, 0);
        private static final int LIMIT_CURRENT_COLOR = Color.rgb(238, 26, 26);
        private final Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG);
        private String voltage = "--.- V";
        private String current = "--.- A";
        private String remaining = "--.- Ah";
        private String status = "Starting";
        private double currentValue;
        private float ampsOut;
        private float ampsIn;

        MetricView(Context context, float ampsOut, float ampsIn) {
            super(context);
            this.ampsOut = ampsOut;
            this.ampsIn = ampsIn;
            paint.setTypeface(android.graphics.Typeface.create("sans", android.graphics.Typeface.BOLD));
        }

        void setMetrics(double voltageValue, double currentValue, double remainingValue) {
            voltage = String.format(Locale.US, "%.1f V", voltageValue);
            current = String.format(Locale.US, "%.1f A", currentValue);
            remaining = String.format(Locale.US, "%.1f Ah", remainingValue);
            this.currentValue = currentValue;
            postInvalidate();
        }

        float getAmpsOut() {
            return ampsOut;
        }

        float getAmpsIn() {
            return ampsIn;
        }

        void setCurrentScale(float ampsOut, float ampsIn) {
            this.ampsOut = ampsOut;
            this.ampsIn = ampsIn;
            postInvalidate();
        }

        void setStatus(String value) {
            status = value;
            postInvalidate();
        }

        @Override
        protected void onDraw(Canvas canvas) {
            int width = getWidth();
            float third = getHeight() / 3.0f;
            drawBand(canvas, Color.rgb(6, 32, 48), 0, third, "VOLTAGE", voltage, width);
            drawBand(canvas, currentColor(), third, third * 2, "CURRENT", current, width);
            drawBand(canvas, Color.rgb(48, 36, 8), third * 2, third * 3, "REMAINING", remaining, width);
            paint.setTextSize(Math.max(20.0f, width * 0.04f));
            paint.setColor(Color.LTGRAY);
            paint.setTextAlign(Paint.Align.CENTER);
            canvas.drawText(status, width / 2.0f, getHeight() - 24.0f, paint);
        }

        private void drawBand(Canvas canvas, int color, float top, float bottom, String label, String value, int width) {
            paint.setColor(color);
            canvas.drawRect(0.0f, top, width, bottom, paint);
            paint.setTextAlign(Paint.Align.CENTER);
            paint.setColor(Color.LTGRAY);
            paint.setTextSize(Math.max(20.0f, width * 0.055f));
            canvas.drawText(label, width / 2.0f, top + (bottom - top) * 0.28f, paint);
            paint.setColor(Color.WHITE);
            paint.setTextSize(Math.max(48.0f, width * 0.18f));
            canvas.drawText(value, width / 2.0f, top + (bottom - top) * 0.67f, paint);
        }

        private int currentColor() {
            double limit = currentValue >= 0.0 ? ampsIn : ampsOut;
            float fraction = (float) Math.min(1.0, Math.abs(currentValue) / limit);
            if (fraction <= 0.5f) {
                return interpolateColor(ZERO_CURRENT_COLOR, MID_CURRENT_COLOR, fraction * 2.0f);
            }
            return interpolateColor(MID_CURRENT_COLOR, LIMIT_CURRENT_COLOR,
                    (fraction - 0.5f) * 2.0f);
        }

        private static int interpolateColor(int start, int end, float fraction) {
            return Color.rgb(
                    blend(Color.red(start), Color.red(end), fraction),
                    blend(Color.green(start), Color.green(end), fraction),
                    blend(Color.blue(start), Color.blue(end), fraction));
        }

        private static int blend(int start, int end, float fraction) {
            return Math.round(start + (end - start) * fraction);
        }
    }
}
