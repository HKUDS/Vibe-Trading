
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
import BoundingRect from 'zrender/lib/core/BoundingRect.js';
import { each } from 'zrender/lib/core/util.js';
import { registerLegacyGridContainLabelImpl } from './Grid.js';
import OrdinalScale from '../../scale/Ordinal.js';
import { makeLabelFormatter } from '../axisHelper.js';
/**
 * [CAUTION] Never export methods other than `installLegacyGridContainLabel`.
 */
export function installLegacyGridContainLabel() {
  registerLegacyGridContainLabelImpl(legacyLayOutGridByContained);
}
/**
 * The input gridRect and axes will be modified.
 */
function legacyLayOutGridByContained(axesList, gridRect) {
  each(axesList, function (axis) {
    if (!axis.model.get(['axisLabel', 'inside'])) {
      var labelUnionRect = estimateLabelUnionRect(axis);
      if (labelUnionRect) {
        var dim = axis.isHorizontal() ? 'height' : 'width';
        var margin = axis.model.get(['axisLabel', 'margin']);
        gridRect[dim] -= labelUnionRect[dim] + margin;
        if (axis.position === 'top') {
          gridRect.y += labelUnionRect.height + margin;
        } else if (axis.position === 'left') {
          gridRect.x += labelUnionRect.width + margin;
        }
      }
    }
  });
}
/**
 * @return Be null/undefined if no labels.
 */
function estimateLabelUnionRect(axis) {
  var axisModel = axis.model;
  var scale = axis.scale;
  if (!axisModel.get(['axisLabel', 'show']) || scale.isBlank()) {
    return;
  }
  var realNumberScaleTicks;
  var tickCount;
  var categoryScaleExtent = scale.getExtent();
  // Optimize for large category data, avoid call `getTicks()`.
  if (scale instanceof OrdinalScale) {
    tickCount = scale.count();
  } else {
    realNumberScaleTicks = scale.getTicks();
    tickCount = realNumberScaleTicks.length;
  }
  var axisLabelModel = axis.getLabelModel();
  var labelFormatter = makeLabelFormatter(axis);
  var rect;
  var step = 1;
  // Simple optimization for large amount of category labels
  if (tickCount > 40) {
    step = Math.ceil(tickCount / 40);
  }
  for (var i = 0; i < tickCount; i += step) {
    var tick = realNumberScaleTicks ? realNumberScaleTicks[i] : {
      value: categoryScaleExtent[0] + i
    };
    var label = labelFormatter(tick, i);
    var unrotatedSingleRect = axisLabelModel.getTextRect(label);
    var singleRect = rotateTextRect(unrotatedSingleRect, axisLabelModel.get('rotate') || 0);
    rect ? rect.union(singleRect) : rect = singleRect;
  }
  return rect;
  function rotateTextRect(textRect, rotate) {
    var rotateRadians = rotate * Math.PI / 180;
    var beforeWidth = textRect.width;
    var beforeHeight = textRect.height;
    var afterWidth = beforeWidth * Math.abs(Math.cos(rotateRadians)) + Math.abs(beforeHeight * Math.sin(rotateRadians));
    var afterHeight = beforeWidth * Math.abs(Math.sin(rotateRadians)) + Math.abs(beforeHeight * Math.cos(rotateRadians));
    var rotatedRect = new BoundingRect(textRect.x, textRect.y, afterWidth, afterHeight);
    return rotatedRect;
  }
}