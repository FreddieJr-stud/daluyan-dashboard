# Root directory for logs
LOG_ROOT = "logs_csv"

# Time windows (24-hour format, inclusive start, exclusive end)
# Example: AM = 4:00–12:00, PM = 12:00–20:00, Off-hours cover the rest

# Time window settings (HH:MM format)
AM_START = "00:00"   # 4:00 AM
PM_START = "12:00"   # 12:00 PM (noon)
PM_END   = "18:00"   # 8:00 PM

# API connection
API_HOST = "CONFIGURE_VESSEL_HOST"
API_PORT = "8481"

# Request endpoints and their intervals (seconds)
REQUEST_INPUTS = [
    ("info", 1),        # every 10 seconds
    ("devices", 10),        # every 10 seconds
    ("SystemSettings", 10),         # every 5 seconds
    ("errors", 1),     # every 1 seconds
    ("vessel", 1),       # every 1 second
    ("Drive", 1),       # every 1 second

    # Motor
    ("device/EVHEV_MC_230400_IP_3_ID_34", 1.0),       # every 1 second
    ("device/EVHEV_MC_230400_IP_3_ID_34_DEVICE", 1.0),       # every 1 second
    ("device/EVHEV_MC_230400_IP_4_ID_34", 1.0),       # every 1 second
    ("device/EVHEV_MC_230400_IP_4_ID_34_DEVICE", 1.0),       # every 1 second

    # Charger
    ("device/BCL25_700_8_CH_IP_3_ID_33", 1.0),          # every 1 second
    ("device/BCL25_700_8_CH_IP_3_ID_33_DEVICE", 1.0),   # every 1 second
    ("device/BCL25_700_8_CH_IP_4_ID_33", 1.0),          # every 1 second
    ("device/BCL25_700_8_CH_IP_4_ID_33_DEVICE", 1.0),   # every 1 second

    # Charger
    ("device/BCL25_700_8_CH_IP_4_ID_81", 1.0),          # every 1 second
    ("device/BCL25_700_8_CH_IP_4_ID_81_DEVICE", 1.0),   # every 1 second
    
    # DCDC
    ("device/HLG_600_IP_3_ID_65", 1),             # every 1 second
    ("device/HLG_600_IP_3_ID_65_DEVICE", 1),      # every 1 second
    
    # Battery Balancing Info
    ("device/OneAries_IP_3_ID_49", 1),       # every 1 second
    ("device/OneAries_IP_3_ID_49_DEVICE", 1),       # every 1 second
    ("device/OneAries_IP_4_ID_49", 1),       # every 1 second
    ("device/OneAries_IP_4_ID_49_DEVICE", 1),       # every 1 second
    
    # Battery Isolation Monitor
    ("device/OneIsoMon_IP_3_ID_50", 1),             # every 1 second
    ("device/OneIsoMon_IP_3_ID_50_DEVICE", 1),      # every 1 second
    ("device/OneIsoMon_IP_4_ID_50", 1),             # every 1 second
    ("device/OneIsoMon_IP_4_ID_50_DEVICE", 1),      # every 1 second
    
    # ("BMWixlsoMon", 1),       # every 1 second
    # ("TqCurrent", 1),       # every 1 second
    # ("Tank", 1),       # every 1 second
    # ("SnS20", 1),       # every 1 second
    # ("Pto", 1),       # every 1 second
    # ("Power2Bank", 1),       # every 1 second
    # ("Polar8340", 1),       # every 1 second
    # ("LvSolar", 1),       # every 1 second
    # ("LvBattery", 1),       # every 1 second
    # ("IsoMon", 1),       # every 1 second
    # ("HLG_600", 1),       # every 1 second
    # ("GenSet", 1),       # every 1 second

    # ("DriveRotation", 1),       # every 1 second
    # ("Drive", 1),       # every 1 second
    # ("DcDc", 1),       # every 1 second
    # ("DcAc", 1),       # every 1 second
    # ("CanGensetDc", 1),       # every 1 second
    # ("Battery", 1),       # every 1 second

]