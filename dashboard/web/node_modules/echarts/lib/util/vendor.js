
/*
* Licensed to the Apache Software Foundation (ASF) under one
* or more contributor license agreements.  See the NOTICE file
* distributed with this work for additional information
* regarding copyright ownership.  The ASF licenses this file
* to you under the Apache License, Version 2.0 (the
* "License"); you may not use this file except in compliance
* with the License.  You may obtain a copy of the License at
*
*   http://www.apache.org/licenses/LICENSE-2.0
*
* Unless required by applicable law or agreed to in writing,
* software distributed under the License is distributed on an
* "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
* KIND, either express or implied.  See the License for the
* specific language governing permissions and limitations
* under the License.
*/


/**
 * AUTO-GENERATED FILE. DO NOT MODIFY.
 */

/*
* Licensed to the Apache Software Foundation (ASF) under one
* or more contributor license agreements.  See the NOTICE file
* distributed with this work for additional information
* regarding copyright ownership.  The ASF licenses this file
* to you under the Apache License, Version 2.0 (the
* "License"); you may not use this file except in compliance
* with the License.  You may obtain a copy of the License at
*
*   http://www.apache.org/licenses/LICENSE-2.0
*
* Unless required by applicable law or agreed to in writing,
* software distributed under the License is distributed on an
* "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
* KIND, either express or implied.  See the License for the
* specific language governing permissions and limitations
* under the License.
*/
import { assert } from 'zrender/lib/core/util.js';
import { error } from './log.js';
import { UNDEFINED_STR } from './types.js';
import { MAX_SAFE_INTEGER } from './number.js';
/* global Int8Array, Int16Array, Int32Array, Uint8Array, Uint16Array, Uint32Array,
   Uint8ClampedArray, Float32Array, Float64Array */
export var Int8ArrayCtor = typeof Int8Array !== UNDEFINED_STR ? Int8Array : undefined;
export var Int16ArrayCtor = typeof Int16Array !== UNDEFINED_STR ? Int16Array : undefined;
export var Int32ArrayCtor = typeof Int32Array !== UNDEFINED_STR ? Int32Array : undefined;
export var Uint8ArrayCtor = typeof Uint8Array !== UNDEFINED_STR ? Uint8Array : undefined;
export var Uint16ArrayCtor = typeof Uint16Array !== UNDEFINED_STR ? Uint16Array : undefined;
export var Uint32ArrayCtor = typeof Uint32Array !== UNDEFINED_STR ? Uint32Array : undefined;
export var Uint8ClampedArrayCtor = typeof Uint8ClampedArray !== UNDEFINED_STR ? Uint8ClampedArray : undefined;
export var Float32ArrayCtor = typeof Float32Array !== UNDEFINED_STR ? Float32Array : undefined;
export var Float64ArrayCtor = typeof Float64Array !== UNDEFINED_STR ? Float64Array : undefined;
export function createFloat32Array(capacity) {
  return tryEnsureTypedArray({
    ctor: Float32ArrayCtor
  }, capacity).arr;
}
export function tryEnsureTypedArray(tyArr,
// Can add more types if needed.
// NOTICE: Callers need to manage data length themselves.
// Do not consider `capacity` as the data length.
capacity) {
  if (process.env.NODE_ENV !== 'production') {
    assert(capacity != null && isFinite(capacity) && capacity >= 0 && tyArr.hasOwnProperty('ctor'));
  }
  var existingArr = tyArr.arr;
  var ctor = tyArr.ctor;
  if (capacity > MAX_SAFE_INTEGER) {
    capacity = MAX_SAFE_INTEGER;
  }
  if (!existingArr || tyArr.typed && existingArr.length < capacity) {
    var nextArr = void 0;
    if (ctor) {
      try {
        // A large contiguous memory allocation may cause OOM.
        nextArr = new ctor(capacity);
        tyArr.typed = true;
        existingArr && nextArr.set(existingArr);
      } catch (e) {
        if (process.env.NODE_ENV !== 'production') {
          error(e);
        }
      }
    }
    if (!nextArr) {
      nextArr = [];
      tyArr.typed = false;
      if (existingArr) {
        for (var i = 0, len = existingArr.length; i < len; i++) {
          nextArr[i] = existingArr[i];
        }
      }
    }
    tyArr.arr = nextArr;
  }
  return tyArr;
}