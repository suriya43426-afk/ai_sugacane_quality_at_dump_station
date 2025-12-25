import os
import sys
import requests
import logging
from PIL import Image
from io import BytesIO

# Setup basic logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def create_shortcut():
    try:
        # 1. Config
        LOGO_URL = "https://www.ocsb.go.th/wp-content/uploads/2024/12/OCSB_logo_circle_180.png"
        BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))) # Root
        ICON_PATH = os.path.join(BASE_DIR, "icon.ico")
        TARGET_BAT = os.path.join(BASE_DIR, "ai_orchestration.bat")
        SHORTCUT_NAME = "AI Sugarcane System.lnk"
        
        # 2. Download and Convert Icon
        if not os.path.exists(ICON_PATH):
            logging.info(f"Downloading logo from {LOGO_URL}...")
            response = requests.get(LOGO_URL)
            if response.status_code == 200:
                img = Image.open(BytesIO(response.content))
                img.save(ICON_PATH, format='ICO', sizes=[(180, 180)])
                logging.info(f"Icon saved to {ICON_PATH}")
            else:
                logging.error(f"Failed to download logo: HTTP {response.status_code}")
                # Continue without icon if download fails? Or exit?
                # User specifically asked for logo, so warning usage.
        
        # 3. Create Shortcut using VBScript wrapper
        # We use a temp vbs file to access WScript.Shell
        desktop = os.path.join(os.path.expanduser("~"), "Desktop")
        link_path = os.path.join(desktop, SHORTCUT_NAME)
        
        vbs_content = f"""
            Set oWS = WScript.CreateObject("WScript.Shell")
            
            ' Desktop Shortcut
            sLinkFile = "{link_path}"
            Set oLink = oWS.CreateShortcut(sLinkFile)
            oLink.TargetPath = "{TARGET_BAT}"
            oLink.WorkingDirectory = "{BASE_DIR}"
            oLink.Description = "Launch AI Sugarcane System"
            oLink.IconLocation = "{ICON_PATH}"
            oLink.Save
            
            ' Startup Shortcut
            sStartup = oWS.SpecialFolders("Startup")
            sStartupLink = sStartup & "\\{SHORTCUT_NAME}"
            Set oStartupLink = oWS.CreateShortcut(sStartupLink)
            oStartupLink.TargetPath = "{TARGET_BAT}"
            oStartupLink.WorkingDirectory = "{BASE_DIR}"
            oStartupLink.Description = "Auto-start AI Sugarcane System"
            oStartupLink.IconLocation = "{ICON_PATH}"
            oStartupLink.Save
        """
        
        vbs_file = os.path.join(BASE_DIR, "create_shortcut_temp.vbs")
        with open(vbs_file, "w") as f:
            f.write(vbs_content)
            
        logging.info("Creating shortcut...")
        os.system(f"cscript //Nologo \"{vbs_file}\"")
        
        # Clean up
        if os.path.exists(vbs_file):
            os.remove(vbs_file)
            
        logging.info(f"Shortcut created successfully at: {link_path}")
        
    except Exception as e:
        logging.error(f"Failed to create shortcut: {e}")
        sys.exit(1)

if __name__ == "__main__":
    create_shortcut()
