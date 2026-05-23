export declare const Int8ArrayCtor: Int8ArrayConstructor;
export declare const Int16ArrayCtor: Int16ArrayConstructor;
export declare const Int32ArrayCtor: Int32ArrayConstructor;
export declare const Uint8ArrayCtor: Uint8ArrayConstructor;
export declare const Uint16ArrayCtor: Uint16ArrayConstructor;
export declare const Uint32ArrayCtor: Uint32ArrayConstructor;
export declare const Uint8ClampedArrayCtor: Uint8ClampedArrayConstructor;
export declare const Float32ArrayCtor: Float32ArrayConstructor;
export declare const Float64ArrayCtor: Float64ArrayConstructor;
export declare type TypedArrayCtor = typeof Int8ArrayCtor | typeof Int16ArrayCtor | typeof Int32ArrayCtor | typeof Uint8ArrayCtor | typeof Uint16ArrayCtor | typeof Uint32ArrayCtor | typeof Uint8ClampedArrayCtor | typeof Float32ArrayCtor | typeof Float64ArrayCtor;
export declare type TypedArrayType = Int8Array | Int16Array | Int32Array | Uint8Array | Uint16Array | Uint32Array | Uint8ClampedArray | Float32Array | Float64Array;
export declare function createFloat32Array(capacity: number): number[] | Float32Array;
/**
 * Use Typed Array if possible for performance optimization, otherwise fallback to a normal array.
 *
 * Usage
 *  const tyArr = tryEnsureCompatibleTypedArray({ctor: Float64ArrayCtor}, capacity);
 */
export declare type CompatibleTypedArray = {
    arr?: TypedArrayType | number[];
    typed?: boolean;
    ctor: TypedArrayCtor;
};
export declare function tryEnsureTypedArray(tyArr: CompatibleTypedArray, capacity: number): CompatibleTypedArray;
