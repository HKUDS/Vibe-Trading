
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
import * as zrUtil from 'zrender/lib/core/util.js';
import { SINGLE_REFERRING } from '../../util/model.js';
import AxisBuilder from '../../component/axis/AxisBuilder.js';
import { isIntervalOrLogScale } from '../../scale/helper.js';
/**
 * [__CAUTION__]
 *  MUST guarantee: if only the input `rect` and `axis.extent` changed,
 *  only `layout.position` changes.
 *  This character is replied on `grid.contain` calculation in `AxisBuilder`.
 *  @see updateCartesianAxisViewCommonPartBuilder
 *
 * Can only be called after coordinate system creation stage.
 * (Can be called before coordinate system update stage).
 */
export function layout(rect, axisModel, opt) {
  opt = opt || {};
  var axis = axisModel.axis;
  var layout = {};
  var otherAxisOnZeroOf = axis.getAxesOnZeroOf()[0];
  var rawAxisPosition = axis.position;
  var axisPosition = otherAxisOnZeroOf ? 'onZero' : rawAxisPosition;
  var axisDim = axis.dim;
  var rectBound = [rect.x, rect.x + rect.width, rect.y, rect.y + rect.height];
  var idx = {
    left: 0,
    right: 1,
    top: 0,
    bottom: 1,
    onZero: 2
  };
  var axisOffset = axisModel.get('offset') || 0;
  var posBound = axisDim === 'x' ? [rectBound[2] - axisOffset, rectBound[3] + axisOffset] : [rectBound[0] - axisOffset, rectBound[1] + axisOffset];
  if (otherAxisOnZeroOf) {
    var onZeroCoord = otherAxisOnZeroOf.toGlobalCoord(otherAxisOnZeroOf.dataToCoord(0));
    posBound[idx.onZero] = Math.max(Math.min(onZeroCoord, posBound[1]), posBound[0]);
  }
  // Axis position
  layout.position = [axisDim === 'y' ? posBound[idx[axisPosition]] : rectBound[0], axisDim === 'x' ? posBound[idx[axisPosition]] : rectBound[3]];
  // Axis rotation
  layout.rotation = Math.PI / 2 * (axisDim === 'x' ? 0 : 1);
  // Tick and label direction, x y is axisDim
  var dirMap = {
    top: -1,
    bottom: 1,
    left: -1,
    right: 1
  };
  layout.labelDirection = layout.tickDirection = layout.nameDirection = dirMap[rawAxisPosition];
  layout.labelOffset = otherAxisOnZeroOf ? posBound[idx[rawAxisPosition]] - posBound[idx.onZero] : 0;
  if (axisModel.get(['axisTick', 'inside'])) {
    layout.tickDirection = -layout.tickDirection;
  }
  if (zrUtil.retrieve(opt.labelInside, axisModel.get(['axisLabel', 'inside']))) {
    layout.labelDirection = -layout.labelDirection;
  }
  // Special label rotation
  var labelRotate = axisModel.get(['axisLabel', 'rotate']);
  layout.labelRotate = axisPosition === 'top' ? -labelRotate : labelRotate;
  // Over splitLine and splitArea
  layout.z2 = 1;
  return layout;
}
export function isCartesian2DDeclaredSeries(seriesModel) {
  return seriesModel.get('coordinateSystem') === 'cartesian2d';
}
/**
 * Note: If pie (or other similar series) use cartesian2d, here
 *  option `seriesModel.get('coordinateSystem') === 'cartesian2d'`
 *  and `seriesModel.coordinateSystem !== cartesian2dCoordSysInstance`
 *  and `seriesModel.boxCoordinateSystem === cartesian2dCoordSysInstance`,
 *  the logic below is probably wrong, therefore skip it temporarily.
 */
export function isCartesian2DInjectedAsDataCoordSys(seriesModel) {
  return seriesModel.coordinateSystem && seriesModel.coordinateSystem.type === 'cartesian2d';
}
export function findAxisModels(seriesModel) {
  var axisModelMap = {
    xAxisModel: null,
    yAxisModel: null
  };
  zrUtil.each(axisModelMap, function (v, key) {
    var axisType = key.replace(/Model$/, '');
    var axisModel = seriesModel.getReferringComponents(axisType, SINGLE_REFERRING).models[0];
    if (process.env.NODE_ENV !== 'production') {
      if (!axisModel) {
        throw new Error(axisType + ' "' + zrUtil.retrieve3(seriesModel.get(axisType + 'Index'), seriesModel.get(axisType + 'Id'), 0) + '" not found');
      }
    }
    axisModelMap[key] = axisModel;
  });
  return axisModelMap;
}
export function createCartesianAxisViewCommonPartBuilder(gridRect, cartesians, axisModel, api, ctx, defaultNameMoveOverlap) {
  var layoutResult = layout(gridRect, axisModel);
  var axisLineAutoShow = false;
  var axisTickAutoShow = false;
  // Not show axisTick or axisLine if other axis is category / time
  for (var i = 0; i < cartesians.length; i++) {
    if (isIntervalOrLogScale(cartesians[i].getOtherAxis(axisModel.axis).scale)) {
      // Still show axis tick or axisLine if other axis is value / log
      axisLineAutoShow = axisTickAutoShow = true;
      if (axisModel.axis.type === 'category' && axisModel.axis.onBand) {
        axisTickAutoShow = false;
      }
    }
  }
  layoutResult.axisLineAutoShow = axisLineAutoShow;
  layoutResult.axisTickAutoShow = axisTickAutoShow;
  layoutResult.defaultNameMoveOverlap = defaultNameMoveOverlap;
  return new AxisBuilder(axisModel, api, layoutResult, ctx);
}
export function updateCartesianAxisViewCommonPartBuilder(axisBuilder, gridRect, axisModel) {
  var newRaw = layout(gridRect, axisModel);
  if (process.env.NODE_ENV !== 'production') {
    var oldRaw_1 = axisBuilder.__getRawCfg();
    zrUtil.each(zrUtil.keys(newRaw), function (prop) {
      if (prop !== 'position' && prop !== 'labelOffset') {
        zrUtil.assert(newRaw[prop] === oldRaw_1[prop]);
      }
    });
  }
  axisBuilder.updateCfg(newRaw);
}
export function getCartesianAxisHashKey(axis) {
  return axis.dim + '_' + axis.index;
}