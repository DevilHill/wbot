import type { Device } from './types';

export function isDeviceAuthorized(device: Pick<Device, 'transport' | 'binding_state'> | undefined): boolean {
  if (!device) return false;
  if (device.transport === 'agent') return device.binding_state === 'approved';
  if (device.transport && device.transport !== 'local') return false;
  return device.binding_state === undefined || device.binding_state === 'approved';
}

export function isDeviceReady(device: Device | undefined): boolean {
  return isDeviceAuthorized(device) && device?.status === 'online' && !device.maintenance;
}
