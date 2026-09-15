"""Device routing and cache compatibility without requiring a physical GPU."""
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from paa_core.asr_worker import DEFAULT_CONFIG, WhisperProvider, config_for_mode
from paa_core.inference_device import apply_device, hardware
from paa_core.model_catalog import CATALOG, MLX_CATALOG
from paa_core.model_manager import ModelManager
from paa_core.repository import DomainError


CPU = {'cpuName': 'Fixture CPU', 'gpuNames': [], 'gpuName': None,
       'gpuAvailable': False, 'gpuBackend': None, 'gpuReason': 'Unavailable'}
APPLE = {**CPU, 'cpuName': 'Apple M5', 'gpuNames': ['Apple M5'], 'gpuName': 'Apple M5',
         'gpuAvailable': True, 'gpuBackend': 'mlx', 'gpuReason': None}


class DeviceTests(unittest.TestCase):
    def tearDown(self):
        hardware.cache_clear()

    def test_windows_requires_usable_cuda_and_reports_both_hardware_names(self):
        info = json.dumps({'cpu': ['Intel Core i7'], 'gpu': ['Intel Graphics', 'NVIDIA RTX']})
        ct2 = SimpleNamespace(get_cuda_device_count=lambda: 1,
                              get_supported_compute_types=lambda _: {'float16'})
        with patch('paa_core.inference_device.sys.platform', 'win32'), \
             patch('paa_core.inference_device.command', side_effect=[info, 'NVIDIA RTX']), \
             patch.dict('sys.modules', {'ctranslate2': ct2}), \
             patch('paa_core.inference_device.ctypes.WinDLL', create=True) as load:
            hardware.cache_clear(); value = hardware()
            self.assertEqual(value['cpuName'], 'Intel Core i7')
            self.assertEqual(value['gpuName'], 'NVIDIA RTX')
            self.assertEqual(value['gpuBackend'], 'cuda')
            self.assertEqual(load.call_count, 2)
        with patch('paa_core.inference_device.sys.platform', 'win32'), \
             patch('paa_core.inference_device.command', return_value=info), \
             patch.dict('sys.modules', {'ctranslate2': ct2}), \
             patch('paa_core.inference_device.ctypes.WinDLL', create=True, side_effect=OSError):
            hardware.cache_clear(); value = hardware()
            self.assertFalse(value['gpuAvailable'])
            self.assertIn('cuDNN', value['gpuReason'])
            self.assertEqual(value['gpuNames'], ['Intel Graphics', 'NVIDIA RTX'])

    def test_cpu_and_cuda_provider_dispatch_uses_requested_device(self):
        model = Mock()
        with patch.dict('sys.modules', {'faster_whisper': SimpleNamespace(WhisperModel=model)}):
            WhisperProvider(Path('/controlled'), DEFAULT_CONFIG)
            self.assertEqual(model.call_args.kwargs['device'], 'cpu')
            cuda = apply_device(config_for_mode('en'), 'gpu', {**APPLE, 'gpuBackend': 'cuda'})
            WhisperProvider(Path('/controlled'), cuda)
            self.assertEqual(model.call_args.kwargs['device'], 'cuda')
            self.assertEqual(model.call_args.kwargs['compute_type'], 'float16')
            self.assertTrue(model.call_args.kwargs['local_files_only'])

    def test_gpu_default_cpu_persistence_and_separate_cache_readiness(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            # Old preferences retain model and language while adopting GPU-first behavior.
            (root / 'transcription-settings.json').write_text(json.dumps({'modelId': 'small', 'language': 'en'}))
            manager = ModelManager(root, Mock(), devices=APPLE)
            try:
                self.assertEqual(manager.status()['device'], 'gpu')
                self.assertEqual(manager.selected()[0], MLX_CATALOG['small']['modelId'])
                self.assertEqual(manager.selected()[2]['backend'], 'mlx')
                self.assertEqual(manager.selected()[2]['beamSize'], 1)
                manager.states['small']['state'] = 'ready'
                # A CPU download must not be mistaken for a usable MLX model.
                self.assertEqual(manager.status()['state'], 'missing')
                with self.assertRaises(DomainError): manager.resolve(*manager.selected()[:2])
                self.assertEqual(manager.resolve(CATALOG['small']['modelId'], CATALOG['small']['revision']), manager.path)
                manager.set_device('cpu')
                selected = manager.selected()
                self.assertEqual(selected[2]['backend'], 'cpu')
                self.assertEqual(manager.status()['state'], 'ready')
                restarted = ModelManager(root, Mock(), devices=APPLE)
                self.assertEqual(restarted.device, 'cpu')
                self.assertEqual(restarted.language, 'en')
                restarted.shutdown()
                manager.set_device('gpu')
                self.assertEqual(selected[2]['backend'], 'cpu')
                self.assertNotEqual(manager.path_for('small'), manager.path)
                manager.states_by_backend['mlx']['small']['state'] = 'ready'
                gpu_path = manager.resolve(*manager.selected()[:2])
                manager.set_device('cpu')
                self.assertEqual(manager.resolve(MLX_CATALOG['small']['modelId'], MLX_CATALOG['small']['revision']), gpu_path)
            finally:
                manager.shutdown()

    def test_unavailable_and_invalid_devices_do_not_change_saved_settings(self):
        with tempfile.TemporaryDirectory() as root:
            manager = ModelManager(Path(root), Mock(), devices=CPU)
            try:
                self.assertEqual(manager.device, 'cpu')
                for device in ('gpu', 'cuda', {}, None):
                    with self.assertRaises(DomainError): manager.set_device(device)
                self.assertFalse(manager.settings_path.exists())
                self.assertEqual(manager.device, 'cpu')
            finally:
                manager.shutdown()

    def test_device_cannot_change_during_model_preparation(self):
        with tempfile.TemporaryDirectory() as root:
            manager = ModelManager(Path(root), Mock(), devices=APPLE)
            manager.thread = Mock()
            with self.assertRaises(DomainError): manager.set_device('cpu')
            self.assertEqual(manager.device, 'gpu')
            manager.thread = None
            manager.shutdown()

    def test_gpu_catalog_is_complete_pinned_and_does_not_replace_cpu_weights(self):
        self.assertEqual(set(MLX_CATALOG), set(CATALOG))
        for key, entry in MLX_CATALOG.items():
            self.assertNotEqual(entry['revision'], CATALOG[key]['revision'])
            self.assertEqual(len(entry['revision']), 40)
            self.assertIn('config.json', entry['files'])
            self.assertTrue({'weights.npz', 'weights.safetensors'} & entry['files'].keys())
            for name, (size, checksum) in entry['files'].items():
                self.assertNotIn('/', name)
                self.assertGreater(size, 0)
                self.assertEqual(len(checksum), 64)
