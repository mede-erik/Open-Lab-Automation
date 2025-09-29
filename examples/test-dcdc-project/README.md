# Test DC-DC Converter - Example Project

This is an example project that demonstrates the measurement variables visualization functionality implemented in the Open Lab Automation software.

## 📋 Description

Project for DC-DC converter efficiency testing with real-time monitoring of main electrical quantities.

## 🔧 Configured Instruments

### Datalogger Keysight 34972A (`DL_Main`)
- **Address**: `TCPIP0::192.168.1.101::inst0::INSTR`
- **Configured channels**:
  - `CH1`: Vin_Monitor (Input voltage, 10:1 attenuation, unit V)
  - `CH2`: Vout_Monitor (Output voltage, unit V)
  - `CH3`: Iin_Monitor (Input current, unit A)
  - `CH4`: Temperature (Temperature, unit °C)

### Multimeter Keysight 34450A (`MM_Bench`)
- **Address**: `TCPIP0::192.168.1.102::inst0::INSTR`
- **Configured channels**:
  - `CH1`: Iout_Precise (Precise output current, unit A)

### Power Supply Keysight E36312A (`PS_Main`)
- **Address**: `TCPIP0::192.168.1.103::inst0::INSTR`
- **Configured channels**:
  - `CH1`: Vin_Supply (0-20V, 0-5A)
  - `CH2`: Vbias_Supply (0-6V, 0-1A)

## 📊 Measurement Display

In the "Remote Control" panel you will see:

```
Vin_Monitor = 12.345 V    Vout_Monitor = 5.012 V
Iin_Monitor = 2.150 A     Temperature = 35.2 °C  
Iout_Precise = 2.050 A
```

### Available Controls

- ✅ **Automatic refresh** with interval slider (1-10s)
- 🔄 **Manual refresh** with dedicated button
- 🎨 **Visual indicators** for instrument connection status
- ⚙️ **Smart formatting** of numeric values

## 🚀 How to Use

1. **Open the project**: File → Open Project → Select `Test DC-DC Converter.json`
2. **Go to Remote Control tab**: Display the measurement panel
3. **Configure refresh**: Use checkbox and slider to set automatic refresh
4. **Monitor measurements**: Variables update automatically

## ⚠️ Important Notes

- **Test addresses**: IP addresses are examples and should be adapted to your network
- **Simulated instruments**: Without real instruments, measurements will show "NC" (Not Connected)
- **Modifiable configuration**: Use the instrument configuration panel to customize

## 🔧 Customization

To adapt this example to your setup:

1. **Modify VISA addresses** in the `test_instruments.inst` file
2. **Update channel parameters**: attenuation, measurement units, variable names
3. **Enable/disable channels** according to your needs
4. **Configure power supply limits** for your application

## 📁 Project Files

- `Test DC-DC Converter.json`: Main project configuration
- `test_instruments.inst`: Detailed instrument configuration

This example demonstrates the complete implementation of the functionality requested in the TODO for measurement variable display!