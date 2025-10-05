"""
Secure database configuration manager.
Handles storage and retrieval of database credentials with password encryption.
Cross-platform support for Linux and Windows.
"""

import os
import json
import platform
from pathlib import Path
from typing import Dict, Any, Optional
from cryptography.fernet import Fernet
import base64
import hashlib


class DatabaseConfigManager:
    """
    Manages secure storage of database configuration.
    
    Features:
    - Cross-platform config directory (Linux/Windows)
    - Password encryption using Fernet symmetric encryption
    - Automatic key generation and storage
    - Migration from old config location
    """
    
    CONFIG_FILENAME = 'database_config.json'
    KEY_FILENAME = '.db_key'
    APP_NAME = 'OpenLabAutomation'
    
    def __init__(self):
        """Initialize database configuration manager."""
        self.config_dir = self._get_config_directory()
        self.config_file = os.path.join(self.config_dir, self.CONFIG_FILENAME)
        self.key_file = os.path.join(self.config_dir, self.KEY_FILENAME)
        
        # Ensure config directory exists
        os.makedirs(self.config_dir, exist_ok=True)
        
        # Initialize encryption key
        self.cipher = self._get_cipher()
    
    def _get_config_directory(self) -> str:
        """
        Get platform-specific configuration directory.
        
        Returns:
            str: Path to configuration directory
            
        Platform locations:
        - Linux: ~/.config/OpenLabAutomation/
        - Windows: %APPDATA%/OpenLabAutomation/
        - macOS: ~/Library/Application Support/OpenLabAutomation/
        """
        system = platform.system()
        
        if system == 'Windows':
            # Windows: use APPDATA
            appdata = os.environ.get('APPDATA')
            if appdata:
                return os.path.join(appdata, self.APP_NAME)
            else:
                # Fallback to user profile
                return os.path.join(Path.home(), 'AppData', 'Roaming', self.APP_NAME)
        
        elif system == 'Darwin':  # macOS
            return os.path.join(Path.home(), 'Library', 'Application Support', self.APP_NAME)
        
        else:  # Linux and others
            # Follow XDG Base Directory specification
            xdg_config = os.environ.get('XDG_CONFIG_HOME')
            if xdg_config:
                return os.path.join(xdg_config, self.APP_NAME)
            else:
                return os.path.join(Path.home(), '.config', self.APP_NAME)
    
    def _get_cipher(self) -> Fernet:
        """
        Get or create encryption cipher.
        
        Returns:
            Fernet: Encryption cipher object
        """
        if os.path.exists(self.key_file):
            # Load existing key
            with open(self.key_file, 'rb') as f:
                key = f.read()
        else:
            # Generate new key
            key = Fernet.generate_key()
            
            # Save key with restricted permissions
            with open(self.key_file, 'wb') as f:
                f.write(key)
            
            # Set file permissions (Unix only)
            if platform.system() != 'Windows':
                os.chmod(self.key_file, 0o600)  # Read/write for owner only
        
        return Fernet(key)
    
    def _encrypt_password(self, password: str) -> str:
        """
        Encrypt password.
        
        Args:
            password: Plain text password
            
        Returns:
            str: Encrypted password (base64 encoded)
        """
        if not password:
            return ''
        
        encrypted = self.cipher.encrypt(password.encode('utf-8'))
        return base64.b64encode(encrypted).decode('utf-8')
    
    def _decrypt_password(self, encrypted_password: str) -> str:
        """
        Decrypt password.
        
        Args:
            encrypted_password: Encrypted password (base64 encoded)
            
        Returns:
            str: Plain text password
        """
        if not encrypted_password:
            return ''
        
        try:
            encrypted = base64.b64decode(encrypted_password.encode('utf-8'))
            decrypted = self.cipher.decrypt(encrypted)
            return decrypted.decode('utf-8')
        except Exception:
            # If decryption fails, might be plain text (migration case)
            return encrypted_password
    
    def load_config(self) -> Dict[str, Any]:
        """
        Load database configuration from file.
        
        Returns:
            dict: Configuration with decrypted password
        """
        default_config = {
            'host': 'localhost',
            'port': 5432,
            'username': 'dcdc_app',
            'password': '',
            'use_ssl': False
        }
        
        # Try to load from new location
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                
                # Decrypt password if present
                if config.get('password'):
                    config['password'] = self._decrypt_password(config['password'])
                
                # Merge with defaults
                default_config.update(config)
                return default_config
                
            except Exception as e:
                print(f"Error loading config: {e}")
                return default_config
        
        # Try to migrate from old location
        old_config_path = self._find_old_config()
        if old_config_path:
            config = self._migrate_old_config(old_config_path)
            if config:
                return config
        
        return default_config
    
    def save_config(self, config: Dict[str, Any]) -> bool:
        """
        Save database configuration to file with encrypted password.
        
        Args:
            config: Configuration dictionary
            
        Returns:
            bool: True if save successful
        """
        try:
            # Create a copy to avoid modifying original
            config_to_save = config.copy()
            
            # Encrypt password before saving
            if config_to_save.get('password'):
                config_to_save['password'] = self._encrypt_password(config_to_save['password'])
            
            # Save to file
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(config_to_save, f, indent=2)
            
            # Set file permissions (Unix only)
            if platform.system() != 'Windows':
                os.chmod(self.config_file, 0o600)  # Read/write for owner only
            
            return True
            
        except Exception as e:
            print(f"Error saving config: {e}")
            return False
    
    def _find_old_config(self) -> Optional[str]:
        """
        Find old configuration file in application directory.
        
        Returns:
            str or None: Path to old config file if found
        """
        # Look for old config in ui directory
        try:
            ui_dir = os.path.join(os.path.dirname(__file__), '..', 'ui')
            old_path = os.path.join(ui_dir, 'database_config.json')
            
            if os.path.exists(old_path):
                return old_path
        except Exception:
            pass
        
        return None
    
    def _migrate_old_config(self, old_path: str) -> Optional[Dict[str, Any]]:
        """
        Migrate configuration from old location.
        
        Args:
            old_path: Path to old configuration file
            
        Returns:
            dict or None: Migrated configuration
        """
        try:
            with open(old_path, 'r', encoding='utf-8') as f:
                old_config = json.load(f)
            
            # Save to new location with encryption
            self.save_config(old_config)
            
            print(f"Migrated database configuration from {old_path}")
            print(f"New location: {self.config_file}")
            
            # Optionally remove old file (commented out for safety)
            # os.remove(old_path)
            
            return old_config
            
        except Exception as e:
            print(f"Error migrating old config: {e}")
            return None
    
    def get_config_location(self) -> str:
        """
        Get path to configuration file.
        
        Returns:
            str: Path to config file
        """
        return self.config_file
    
    def test_encryption(self) -> bool:
        """
        Test encryption/decryption functionality.
        
        Returns:
            bool: True if encryption works correctly
        """
        test_password = "test_password_123!@#"
        
        try:
            encrypted = self._encrypt_password(test_password)
            decrypted = self._decrypt_password(encrypted)
            return decrypted == test_password
        except Exception:
            return False
    
    def get_connection_params(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Get connection parameters ready for database connection.
        Password is already decrypted by load_config().
        
        Args:
            config: Configuration dictionary from load_config()
            
        Returns:
            dict: Connection parameters
        """
        params = {
            'host': config.get('host', 'localhost'),
            'port': config.get('port', 5432),
            'username': config.get('username', 'dcdc_app'),
            'password': config.get('password', '')
        }
        
        if config.get('use_ssl', False):
            params['sslmode'] = 'require'
        
        return params


# Singleton instance
_config_manager = None

def get_database_config_manager() -> DatabaseConfigManager:
    """
    Get singleton instance of DatabaseConfigManager.
    
    Returns:
        DatabaseConfigManager: Singleton instance
    """
    global _config_manager
    if _config_manager is None:
        _config_manager = DatabaseConfigManager()
    return _config_manager
