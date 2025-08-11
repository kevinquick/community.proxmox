# -*- coding: utf-8 -*-
#
# Copyright (c) 2021, Ansible Project
# GNU General Public License v3.0+ (see LICENSES/GPL-3.0-or-later.txt or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import absolute_import, division, print_function

__metaclass__ = type

from unittest.mock import patch, MagicMock

import pytest

proxmoxer = pytest.importorskip("proxmoxer")

from ansible_collections.community.proxmox.plugins.modules import proxmox_kvm
from ansible_collections.community.internal_test_tools.tests.unit.plugins.modules.utils import (
    AnsibleExitJson,
    AnsibleFailJson,
    ModuleTestCase,
    set_module_args,
)
import ansible_collections.community.proxmox.plugins.module_utils.proxmox as proxmox_utils


class TestProxmoxKvmModule(ModuleTestCase):
    def setUp(self):
        super(TestProxmoxKvmModule, self).setUp()
        proxmox_utils.HAS_PROXMOXER = True
        self.module = proxmox_kvm
        self.mock_api = MagicMock()
        self.connect_mock = patch(
            "ansible_collections.community.proxmox.plugins.module_utils.proxmox.ProxmoxAnsible._connect",
            return_value=self.mock_api
        ).start()
        
        self.get_node_mock = patch.object(
            proxmox_utils.ProxmoxAnsible, "get_node", return_value=True
        ).start()
        self.get_vm_mock = patch.object(proxmox_utils.ProxmoxAnsible, "get_vm").start()
        self.create_vm_mock = patch.object(
            proxmox_kvm.ProxmoxKvmAnsible, "create_vm", return_value=True
        ).start()

    def tearDown(self):
        for mock in [self.create_vm_mock, self.get_vm_mock, self.get_node_mock, self.connect_mock]:
            mock.stop()
        super(TestProxmoxKvmModule, self).tearDown()

    def _base_module_args(self, **kwargs):
        return {"api_host": "host", "api_user": "user", "api_password": "password", **kwargs}

    def test_module_fail_when_required_args_missing(self):
        with self.assertRaises(AnsibleFailJson):
            with set_module_args({}):
                self.module.main()

    def test_module_exits_unchaged_when_provided_vmid_exists(self):
        with set_module_args(self._base_module_args(vmid="100", node="pve")):
            self.get_vm_mock.return_value = [{"vmid": "100"}]
            with pytest.raises(AnsibleExitJson) as exc_info:
                self.module.main()

        self.get_vm_mock.assert_called_once()
        result = exc_info.value.args[0]
        assert result["changed"] is False
        assert result["msg"] == "VM with vmid <100> already exists"

    def test_vm_created_when_vmid_not_exist_but_name_already_exist(self):
        with set_module_args(self._base_module_args(vmid="100", name="existing.vm.local", node="pve")):
            self.get_vm_mock.return_value = None
            with pytest.raises(AnsibleExitJson) as exc_info:
                self.module.main()

        self.get_vm_mock.assert_called_once()
        self.get_node_mock.assert_called_once()
        self.create_vm_mock.assert_called_once()
        result = exc_info.value.args[0]
        assert result["changed"] is True
        assert result["msg"] == "VM existing.vm.local with vmid 100 deployed"

    @patch.object(proxmox_utils.ProxmoxAnsible, "get_vmid")
    def test_vm_not_created_when_name_already_exist_and_vmid_not_set(self, get_vmid_mock):
        get_vmid_mock.return_value = {"vmid": 100, "name": "existing.vm.local"}
        
        with set_module_args(self._base_module_args(name="existing.vm.local", node="pve")):
            with pytest.raises(AnsibleExitJson) as exc_info:
                self.module.main()

        get_vmid_mock.assert_called_once()
        result = exc_info.value.args[0]
        assert result["changed"] is False

    @patch.object(proxmox_utils.ProxmoxAnsible, "get_nextvmid", return_value=101)
    @patch.object(proxmox_utils.ProxmoxAnsible, "get_vmid", return_value=None)
    def test_vm_created_when_name_doesnt_exist_and_vmid_not_set(self, get_vmid_mock, get_nextvmid_mock):
        with set_module_args(self._base_module_args(name="existing.vm.local", node="pve")):
            self.get_vm_mock.return_value = None
            with pytest.raises(AnsibleExitJson) as exc_info:
                self.module.main()

        get_vmid_mock.assert_called_once()
        get_nextvmid_mock.assert_called_once()
        result = exc_info.value.args[0]
        assert result["changed"] is True
        assert result["msg"] == "VM existing.vm.local with vmid 101 deployed"

    def test_parse_mac(self):
        assert (
            proxmox_kvm.parse_mac("virtio=00:11:22:AA:BB:CC,bridge=vmbr0,firewall=1")
            == "00:11:22:AA:BB:CC"
        )

    def test_parse_dev(self):
        test_cases = [
            ("local-lvm:vm-1000-disk-0,format=qcow2", "local-lvm:vm-1000-disk-0"),
            ("local-lvm:vm-101-disk-1,size=8G", "local-lvm:vm-101-disk-1"),
            ("local-zfs:vm-1001-disk-0", "local-zfs:vm-1001-disk-0"),
        ]
        for disk_string, expected_dev in test_cases:
            assert proxmox_kvm.parse_dev(disk_string) == expected_dev

    @patch.object(proxmox_kvm.ProxmoxKvmAnsible, 'migrate_vm')
    def test_migration_with_local_disks(self, migrate_vm_mock):
        with set_module_args(self._base_module_args(vmid=100, node="target-node", migrate=True, with_local_disks=True)):
            self.get_vm_mock.return_value = {'vmid': 100, 'node': 'source-node'}
            with pytest.raises(AnsibleExitJson) as exc_info:
                self.module.main()
        
        migrate_vm_mock.assert_called_once()
        call_args = migrate_vm_mock.call_args
        assert call_args[0] == ({'vmid': 100, 'node': 'source-node'}, 'target-node')
        assert call_args[1]['with_local_disks'] is True
        result = exc_info.value.args[0]
        assert result['changed'] is True
        assert "migrated from source-node to target-node" in result['msg']

    @patch.object(proxmox_kvm.ProxmoxKvmAnsible, 'wait_for_task', return_value=True)
    def test_migrate_vm_api_call(self, wait_for_task_mock):
        self.mock_api.nodes.return_value.qemu.return_value.migrate.post.return_value = 'UPID:test'
        
        kvm_ansible = proxmox_kvm.ProxmoxKvmAnsible(None)
        kvm_ansible.proxmox_api = self.mock_api
        vm = {'vmid': 100, 'node': 'source-node'}
        
        assert kvm_ansible.migrate_vm(vm, 'target-node', with_local_disks=True, migrate_speed=100)
        self.mock_api.nodes.return_value.qemu.return_value.migrate.post.assert_called_with(
            vmid=100, node='source-node', target='target-node', online=1,
            **{'with-local-disks': 1, 'bwlimit': 102400}
        )
        wait_for_task_mock.assert_called_once()
