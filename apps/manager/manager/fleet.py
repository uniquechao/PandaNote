"""Device identity resolves storage; no URL/version can choose another root."""
from dataclasses import dataclass
from pathlib import Path
import re
import threading
from .store import Store
from .service import ManagerService
from .caldav_provider import CalDAVProvider

class DeviceScopes:
    def __init__(self,root,profile):
        self.root=Path(root).absolute();self.profile=profile
    def bind_legacy(self):
        store=Store(self.root)
        if store.load_value('legacy_device_id') is None and len(self.profile.device_credentials)==1:
            store.save_value('legacy_device_id',next(iter(self.profile.device_credentials)))
    def root_for(self,device_id):
        if not isinstance(device_id,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}',device_id) or device_id not in self.profile.device_credentials:
            raise ValueError('unknown device')
        legacy=Store(self.root).load_value('legacy_device_id')
        if legacy==device_id or (legacy is None and len(self.profile.device_credentials)==1):return self.root
        return self.root/'devices'/device_id

@dataclass
class DeviceBundle:
    service:ManagerService
    coordinator:object

class DeviceFleet(DeviceScopes):
    def __init__(self,root,profile,legacy_service,legacy_coordinator,coordinator_factory):
        super().__init__(root,profile);self.legacy_service=legacy_service;self.legacy_coordinator=legacy_coordinator
        self.factory=coordinator_factory;self.bundles={};self.lock=threading.RLock();self.started=False
    def bundle(self,device_id):
        directory=self.root_for(device_id)
        with self.lock:
            if device_id not in self.bundles:
                if directory==self.root:bundle=DeviceBundle(self.legacy_service,self.legacy_coordinator)
                else:
                    service=ManagerService(directory,CalDAVProvider(directory),default_timezone='Asia/Singapore')
                    bundle=DeviceBundle(service,self.factory(service))
                self.bundles[device_id]=bundle
                if self.started and bundle.coordinator is not self.legacy_coordinator:bundle.coordinator.start()
            return self.bundles[device_id]
    def start(self):
        self.bind_legacy()
        for device_id in self.profile.device_credentials:self.bundle(device_id)
        with self.lock:
            self.started=True
            for bundle in self.bundles.values():
                if bundle.coordinator is not self.legacy_coordinator:bundle.coordinator.start()
    def stop(self):
        with self.lock:
            self.started=False
            bundles=list(self.bundles.values())
        for bundle in bundles:
            if bundle.coordinator is not self.legacy_coordinator:bundle.coordinator.stop()
    def devices(self):
        result=[]
        for device_id in self.profile.device_credentials:
            bundle=self.bundle(device_id);value=bundle.service.status()
            if value.get('error'):value['error']={'code':'calendar_failure','message':'此设备日历来源暂不可用，已有内容已保留。'}
            result.append(dict(id=device_id,name='PandaNote · '+device_id,status=value))
        return result
