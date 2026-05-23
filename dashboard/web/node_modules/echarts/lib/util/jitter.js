
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
import { calcBandWidth } from '../coord/axisBand.js';
import Axis2D from '../coord/cartesian/Axis2D.js';
import { COORD_SYS_TYPE_CARTESIAN_2D } from '../coord/cartesian/GridModel.js';
import { COORD_SYS_TYPE_SINGLE } from '../coord/single/AxisModel.js';
import { isOrdinalScale } from '../scale/helper.js';
import { makeInner } from './model.js';
export function needFixJitter(seriesModel, axis) {
  var coordinateSystem = seriesModel.coordinateSystem;
  var coordType = coordinateSystem && coordinateSystem.type;
  var baseAxis = coordinateSystem && coordinateSystem.getBaseAxis && coordinateSystem.getBaseAxis();
  var scaleType = baseAxis && baseAxis.scale && baseAxis.scale.type;
  var seriesValid = coordType === COORD_SYS_TYPE_CARTESIAN_2D && scaleType === 'ordinal' || coordType === COORD_SYS_TYPE_SINGLE;
  var axisValid = axis.model.get('jitter') > 0;
  return seriesValid && axisValid;
}
var inner = makeInner();
/**
 * Fix jitter for overlapping data points.
 *
 * @param fixedAxis The axis whose coord doesn't change with jitter.
 * @param fixedCoord The coord of fixedAxis.
 * @param floatCoord The coord of the other axis, which should be changed with jittering.
 * @param radius The radius of the data point, considering the symbol is a circle.
 * @returns updated floatCoord.
 */
export function fixJitter(fixedAxis, fixedCoord, floatCoord, radius) {
  if (fixedAxis instanceof Axis2D) {
    var scaleType = fixedAxis.scale.type;
    if (scaleType !== 'ordinal') {
      return floatCoord;
    }
  }
  var axisModel = fixedAxis.model;
  var jitter = axisModel.get('jitter');
  if (!(jitter > 0)) {
    return floatCoord;
  }
  var jitterOverlap = axisModel.get('jitterOverlap');
  var jitterMargin = axisModel.get('jitterMargin') || 0;
  // Get band width to limit jitter range
  var bandWidth = isOrdinalScale(fixedAxis.scale) ? calcBandWidth(fixedAxis).w : null;
  if (jitterOverlap) {
    return fixJitterIgnoreOverlaps(floatCoord, jitter, bandWidth, radius);
  }
  return fixJitterAvoidOverlaps(fixedAxis, fixedCoord, floatCoord, radius, jitter, jitterMargin);
}
function fixJitterIgnoreOverlaps(floatCoord, jitter, bandWidth, radius) {
  // Don't clamp single axis
  if (bandWidth === null) {
    return floatCoord + (Math.random() - 0.5) * jitter;
  }
  var maxJitter = bandWidth - radius * 2;
  var actualJitter = Math.min(Math.max(0, jitter), maxJitter);
  return floatCoord + (Math.random() - 0.5) * actualJitter;
}
function fixJitterAvoidOverlaps(fixedAxis, fixedCoord, floatCoord, radius, jitter, margin) {
  var store = inner(fixedAxis);
  if (!store.items) {
    store.items = [];
  }
  var items = store.items;
  // Try both positive and negative directions, choose the one with smaller movement
  var overlapA = placeJitterOnDirection(items, fixedCoord, floatCoord, radius, jitter, margin, 1);
  var overlapB = placeJitterOnDirection(items, fixedCoord, floatCoord, radius, jitter, margin, -1);
  var minFloat = Math.abs(overlapA - floatCoord) < Math.abs(overlapB - floatCoord) ? overlapA : overlapB;
  // Clamp only category axis
  var bandWidth = isOrdinalScale(fixedAxis.scale) ? calcBandWidth(fixedAxis).w : null;
  var distance = Math.abs(minFloat - floatCoord);
  if (distance > jitter / 2 || bandWidth && distance > bandWidth / 2 - radius) {
    // If the new item is moved too far, then give up.
    // Fall back to random jitter.
    return fixJitterIgnoreOverlaps(floatCoord, jitter, bandWidth, radius);
  }
  // Add new point to array
  items.push({
    fixedCoord: fixedCoord,
    floatCoord: minFloat,
    r: radius
  });
  return minFloat;
}
function placeJitterOnDirection(items, fixedCoord, floatCoord, radius, jitter, margin, direction) {
  var y = floatCoord;
  // Check all existing items for overlap and find the maximum adjustment needed
  for (var i = 0; i < items.length; i++) {
    var item = items[i];
    var dx = fixedCoord - item.fixedCoord;
    var dy = y - item.floatCoord;
    var d2 = dx * dx + dy * dy;
    var r = radius + item.r + margin;
    if (d2 < r * r) {
      // Has overlap, calculate required adjustment
      var requiredY = item.floatCoord + Math.sqrt(r * r - dx * dx) * direction;
      // Check if this adjustment would move too far
      if (Math.abs(requiredY - floatCoord) > jitter / 2) {
        return Number.MAX_VALUE; // Give up
      }
      // Update y only when it's larger to the center
      if (direction === 1 && requiredY > y || direction === -1 && requiredY < y) {
        y = requiredY;
        // Loop from the start again
        i = -1; // Reset index to recheck all items
        continue; // Recalculate with the new y position
      }
    }
  }
  return y;
}