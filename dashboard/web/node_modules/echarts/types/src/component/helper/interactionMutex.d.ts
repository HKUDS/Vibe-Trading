import { ZRenderType } from 'zrender/lib/zrender.js';
declare type InteractionMutexResource = {
    globalPan: string;
};
export declare function take(zr: ZRenderType, resourceKey: keyof InteractionMutexResource, userKey: InteractionMutexResource[keyof InteractionMutexResource]): void;
export declare function release(zr: ZRenderType, resourceKey: keyof InteractionMutexResource, userKey: InteractionMutexResource[keyof InteractionMutexResource]): void;
export declare function isTaken(zr: ZRenderType, resourceKey: keyof InteractionMutexResource): boolean;
export {};
