
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
/**
 * Grid is a region which contains at most 4 cartesian systems
 *
 * TODO Default cartesian
 */
import { isObject, each, indexOf, retrieve3, keys, assert, eqNaN, find, retrieve2, hasOwn } from 'zrender/lib/core/util.js';
import { createBoxLayoutReference, getLayoutRect } from '../../util/layout.js';
import { createScaleByModel, getScaleValuePositionKind, isNameLocationCenter, shouldAxisShow, retrieveAxisBreaksOption, determineAxisType, isOnAxisZeroDiscouraged, SCALE_VALUE_POSITION_KIND_OUTSIDE, getTickValueOutermost, isAxisOnBand } from '../../coord/axisHelper.js';
import Cartesian2D, { cartesian2DDimensions } from './Cartesian2D.js';
import Axis2D from './Axis2D.js';
import { SINGLE_REFERRING } from '../../util/model.js';
// Depends on GridModel, AxisModel, which performs preprocess.
import { COORD_SYS_TYPE_CARTESIAN_2D, OUTER_BOUNDS_CLAMP_DEFAULT, OUTER_BOUNDS_DEFAULT } from './GridModel.js';
import { findAxisModels, createCartesianAxisViewCommonPartBuilder, updateCartesianAxisViewCommonPartBuilder } from './cartesianAxisHelper.js';
import { isIntervalOrLogScale, isOrdinalScale } from '../../scale/helper.js';
import { scaleCalcAlign } from '../axisAlignTicks.js';
import { expandOrShrinkRect, WH, XY } from '../../util/graphic.js';
import { AxisBuilderSharedContext, resolveAxisNameOverlapDefault, moveIfOverlapByLinearLabels, getLabelInner } from '../../component/axis/AxisBuilder.js';
import { error, log } from '../../util/log.js';
import { AxisTickLabelComputingKind } from '../axisTickLabelBuilder.js';
import { injectCoordSysByOption } from '../../core/CoordinateSystem.js';
import { mathMax, parsePositionSizeOption } from '../../util/number.js';
import { scaleCalcNice } from '../axisNiceTicks.js';
import { createDimNameMap } from '../../data/helper/SeriesDataSchema.js';
import { AXIS_EXTENT_INFO_BUILD_FROM_COORD_SYS_UPDATE, scaleRawExtentInfoEnableBoxCoordSysUsage, scaleRawExtentInfoCreate } from '../scaleRawExtentInfo.js';
import { hasBreaks } from '../../scale/break.js';
import { associateSeriesWithAxis } from '../axisStatistics.js';
// margin is [top, right, bottom, left]
var XY_TO_MARGIN_IDX = [[3, 1], [0, 2] // xyIdx 1 => 'y'
];
var Grid = /** @class */function () {
  function Grid(gridModel, ecModel, api) {
    // FIXME:TS where used (different from registered type 'cartesian2d')?
    this.type = 'grid';
    this._coordsMap = {};
    this._coordsList = [];
    this._axesMap = {};
    this._axesList = [];
    this.axisPointerEnabled = true;
    this.dimensions = cartesian2DDimensions;
    this._initCartesian(gridModel, ecModel, api);
    this.model = gridModel;
  }
  Grid.prototype.getRect = function () {
    return this._rect;
  };
  Grid.prototype.update = function (ecModel, api) {
    var axesMap = this._axesMap;
    each(this._axesList, function (axis) {
      scaleRawExtentInfoCreate(axis, AXIS_EXTENT_INFO_BUILD_FROM_COORD_SYS_UPDATE);
      var scale = axis.scale;
      if (isOrdinalScale(scale)) {
        scale.setSortInfo(axis.model.get('categorySortInfo'));
      }
    });
    function updateAxisTicks(axes) {
      // Axis is added in order of axisIndex.
      var axesIndices = keys(axes);
      var axisNeedsAlign = [];
      for (var i = axesIndices.length - 1; i >= 0; i--) {
        // Reverse order
        var axis = axes[+axesIndices[i]];
        if (axis.__alignTo) {
          axisNeedsAlign.push(axis);
        } else {
          scaleCalcNice(axis);
        }
      }
      ;
      each(axisNeedsAlign, function (axis) {
        if (incapableOfAlignNeedFallback(axis, axis.__alignTo)) {
          scaleCalcNice(axis);
        } else {
          scaleCalcAlign(axis, axis.__alignTo.scale);
        }
      });
    }
    updateAxisTicks(axesMap.x);
    updateAxisTicks(axesMap.y);
    // Key: axisDim_axisIndex, value: boolean, whether onZero target.
    var onZeroRecords = {};
    each(axesMap.x, function (xAxis) {
      fixAxisOnZero(axesMap, 'y', xAxis, onZeroRecords);
    });
    each(axesMap.y, function (yAxis) {
      fixAxisOnZero(axesMap, 'x', yAxis, onZeroRecords);
    });
    // Resize again if containLabel is enabled
    // FIXME It may cause getting wrong grid size in data processing stage
    this.resize(this.model, api);
  };
  /**
   * Resize the grid.
   *
   * [NOTE]
   * If both "grid.containLabel/grid.contain" and pixel-required-data-processing (such as, "dataSampling")
   * exist, circular dependency occurs in logic.
   * The final compromised sequence is:
   *  1. Calculate "axis.extent" (pixel extent) and AffineTransform based on only "grid layout options".
   *      Not accurate if "grid.containLabel/grid.contain" is required, but it is a compromise to avoid
   *      circular dependency.
   *  2. Perform "series data processing" (where "dataSampling" requires "axis.extent").
   *  3. Calculate "scale.extent" (data extent) based on "processed series data".
   *  4. Modify "axis.extent" for "grid.containLabel/grid.contain":
   *      4.1. Calculate "axis labels" based on "scale.extent".
   *      4.2. Modify "axis.extent" by the bounding rects of "axis labels and names".
   */
  Grid.prototype.resize = function (gridModel, api, beforeDataProcessing) {
    var layoutRef = createBoxLayoutReference(gridModel, api);
    var gridRect = this._rect = getLayoutRect(gridModel.getBoxLayoutParams(), layoutRef.refContainer);
    // PENDING: whether to support that if the input `coord` is out of the base coord sys,
    //  do not render anything. At present, the behavior is undefined.
    var axesMap = this._axesMap;
    var coordsList = this._coordsList;
    var optionContainLabel = gridModel.get('containLabel'); // No `.get(, true)` for backward compat.
    // NOTE: The axis pixel extent is also required by some estimation, e.g., in coord sys update stage,
    // bars on 'time'/'value' axis need it to calculate the supplementary scale extent to avoid edge bars
    // overflowing the axis (see `barGrid.ts`). Therefore, axis pixel extent need to be set early, even
    // may not be accurate.
    updateAllAxisExtentTransByGridRect(axesMap, gridRect);
    if (!beforeDataProcessing) {
      var axisBuilderSharedCtx = createAxisBiulders(gridRect, coordsList, axesMap, optionContainLabel, api);
      var noPxChange = void 0;
      if (optionContainLabel) {
        if (legacyLayOutGridByContainLabel) {
          // console.time('legacyLayOutGridByContainLabel');
          legacyLayOutGridByContainLabel(this._axesList, gridRect);
          updateAllAxisExtentTransByGridRect(axesMap, gridRect);
          // console.timeEnd('legacyLayOutGridByContainLabel');
        } else {
          if (process.env.NODE_ENV !== 'production') {
            log('Specified `grid.containLabel` but no `use(LegacyGridContainLabel)`;' + 'use `grid.outerBounds` instead.', true);
          }
          noPxChange = layOutGridByOuterBounds(gridRect.clone(), 'axisLabel', null, gridRect, axesMap, axisBuilderSharedCtx, layoutRef);
        }
      } else {
        var _a = prepareOuterBounds(gridModel, gridRect, layoutRef),
          outerBoundsRect = _a.outerBoundsRect,
          parsedOuterBoundsContain = _a.parsedOuterBoundsContain,
          outerBoundsClamp = _a.outerBoundsClamp;
        if (outerBoundsRect) {
          // console.time('layOutGridByOuterBounds');
          noPxChange = layOutGridByOuterBounds(outerBoundsRect, parsedOuterBoundsContain, outerBoundsClamp, gridRect, axesMap, axisBuilderSharedCtx, layoutRef);
          // console.timeEnd('layOutGridByOuterBounds');
        }
      }
      // console.time('buildAxesView_determine');
      createOrUpdateAxesView(gridRect, axesMap, AxisTickLabelComputingKind.determine, null, noPxChange, layoutRef);
      // console.timeEnd('buildAxesView_determine');
      each(this._coordsList, function (coord) {
        // Calculate affine matrix to accelerate the data to point transform.
        // If all the axes scales are time or value.
        coord.calcAffineTransform();
      });
    } // End of beforeDataProcessing
  };
  Grid.prototype.getAxis = function (dim, axisIndex) {
    var axesMapOnDim = this._axesMap[dim];
    if (axesMapOnDim != null) {
      return axesMapOnDim[axisIndex || 0];
    }
  };
  Grid.prototype.getAxes = function () {
    return this._axesList.slice();
  };
  Grid.prototype.getCartesian = function (xAxisIndex, yAxisIndex) {
    if (xAxisIndex != null && yAxisIndex != null) {
      var key = 'x' + xAxisIndex + 'y' + yAxisIndex;
      return this._coordsMap[key];
    }
    if (isObject(xAxisIndex)) {
      yAxisIndex = xAxisIndex.yAxisIndex;
      xAxisIndex = xAxisIndex.xAxisIndex;
    }
    for (var i = 0, coordList = this._coordsList; i < coordList.length; i++) {
      if (coordList[i].getAxis('x').index === xAxisIndex || coordList[i].getAxis('y').index === yAxisIndex) {
        return coordList[i];
      }
    }
  };
  Grid.prototype.getCartesians = function () {
    return this._coordsList.slice();
  };
  /**
   * @implements
   */
  Grid.prototype.convertToPixel = function (ecModel, finder, value) {
    var target = this._findConvertTarget(finder);
    return target.cartesian ? target.cartesian.dataToPoint(value) : target.axis ? target.axis.toGlobalCoord(target.axis.dataToCoord(value)) : null;
  };
  /**
   * @implements
   */
  Grid.prototype.convertFromPixel = function (ecModel, finder, value) {
    var target = this._findConvertTarget(finder);
    return target.cartesian ? target.cartesian.pointToData(value) : target.axis ? target.axis.coordToData(target.axis.toLocalCoord(value)) : null;
  };
  Grid.prototype._findConvertTarget = function (finder) {
    var seriesModel = finder.seriesModel;
    var xAxisModel = finder.xAxisModel || seriesModel && seriesModel.getReferringComponents('xAxis', SINGLE_REFERRING).models[0];
    var yAxisModel = finder.yAxisModel || seriesModel && seriesModel.getReferringComponents('yAxis', SINGLE_REFERRING).models[0];
    var gridModel = finder.gridModel;
    var coordsList = this._coordsList;
    var cartesian;
    var axis;
    if (seriesModel) {
      cartesian = seriesModel.coordinateSystem;
      indexOf(coordsList, cartesian) < 0 && (cartesian = null);
    } else if (xAxisModel && yAxisModel) {
      cartesian = this.getCartesian(xAxisModel.componentIndex, yAxisModel.componentIndex);
    } else if (xAxisModel) {
      axis = this.getAxis('x', xAxisModel.componentIndex);
    } else if (yAxisModel) {
      axis = this.getAxis('y', yAxisModel.componentIndex);
    }
    // Lowest priority.
    else if (gridModel) {
      var grid = gridModel.coordinateSystem;
      if (grid === this) {
        cartesian = this._coordsList[0];
      }
    }
    return {
      cartesian: cartesian,
      axis: axis
    };
  };
  /**
   * @implements
   */
  Grid.prototype.containPoint = function (point) {
    var coord = this._coordsList[0];
    if (coord) {
      return coord.containPoint(point);
    }
  };
  /**
   * Initialize cartesian coordinate systems
   */
  Grid.prototype._initCartesian = function (gridModel, ecModel, api) {
    var _this = this;
    var grid = this;
    var axisPositionUsed = {
      left: false,
      right: false,
      top: false,
      bottom: false
    };
    var axesMap = {
      x: {},
      y: {}
    };
    var axesCount = {
      x: 0,
      y: 0
    };
    // Create axis
    ecModel.eachComponent('xAxis', createAxisCreator('x'), this);
    ecModel.eachComponent('yAxis', createAxisCreator('y'), this);
    if (!axesCount.x || !axesCount.y) {
      // Roll back when there no either x or y axis
      this._axesMap = {};
      this._axesList = [];
      return;
    }
    this._axesMap = axesMap;
    // Create cartesian2d
    each(axesMap.x, function (xAxis, xAxisIndex) {
      each(axesMap.y, function (yAxis, yAxisIndex) {
        var key = 'x' + xAxisIndex + 'y' + yAxisIndex;
        var cartesian = new Cartesian2D(key);
        cartesian.master = _this;
        cartesian.model = gridModel;
        _this._coordsMap[key] = cartesian;
        _this._coordsList.push(cartesian);
        cartesian.addAxis(xAxis);
        cartesian.addAxis(yAxis);
      });
    });
    prepareAlignToInCoordSysCreate(axesMap.x);
    prepareAlignToInCoordSysCreate(axesMap.y);
    function createAxisCreator(dimName) {
      return function (axisModel, idx) {
        if (!isAxisUsedInTheGrid(axisModel, gridModel)) {
          return;
        }
        var axisPosition = axisModel.get('position');
        if (dimName === 'x') {
          // Fix position
          if (axisPosition !== 'top' && axisPosition !== 'bottom') {
            // Default bottom of X
            axisPosition = axisPositionUsed.bottom ? 'top' : 'bottom';
          }
        } else {
          // Fix position
          if (axisPosition !== 'left' && axisPosition !== 'right') {
            // Default left of Y
            axisPosition = axisPositionUsed.left ? 'right' : 'left';
          }
        }
        axisPositionUsed[axisPosition] = true;
        var axisType = determineAxisType(axisModel);
        var axis = new Axis2D(dimName, createScaleByModel(axisModel, axisType, true), [0, 0], axisType, axisPosition);
        axis.onBand = isAxisOnBand(axis.scale, axisModel);
        axis.inverse = axisModel.get('inverse');
        // Inject axis into axisModel
        axisModel.axis = axis;
        // Inject axisModel into axis
        axis.model = axisModel;
        // Inject grid info axis
        axis.grid = grid;
        // Index of axis, can be used as key
        axis.index = idx;
        grid._axesList.push(axis);
        axesMap[dimName][idx] = axis;
        axesCount[dimName]++;
      };
    }
  };
  /**
   * @param dim 'x' or 'y' or 'auto' or null/undefined
   */
  Grid.prototype.getTooltipAxes = function (dim) {
    var baseAxes = [];
    var otherAxes = [];
    each(this.getCartesians(), function (cartesian) {
      var baseAxis = dim != null && dim !== 'auto' ? cartesian.getAxis(dim) : cartesian.getBaseAxis();
      var otherAxis = cartesian.getOtherAxis(baseAxis);
      indexOf(baseAxes, baseAxis) < 0 && baseAxes.push(baseAxis);
      indexOf(otherAxes, otherAxis) < 0 && otherAxes.push(otherAxis);
    });
    return {
      baseAxes: baseAxes,
      otherAxes: otherAxes
    };
  };
  Grid.create = function (ecModel, api) {
    var grids = [];
    ecModel.eachComponent('grid', function (gridModel, idx) {
      var grid = new Grid(gridModel, ecModel, api);
      grid.name = 'grid_' + idx;
      // dataSampling requires axis extent, so resize
      // should be performed in create stage.
      grid.resize(gridModel, api, true);
      gridModel.coordinateSystem = grid;
      grids.push(grid);
      each(grid._axesList, function (axis) {
        scaleRawExtentInfoEnableBoxCoordSysUsage(axis, Grid.dimIdxMap);
      });
    });
    // Inject the coordinateSystems into seriesModel
    ecModel.eachSeries(function (seriesModel) {
      var xAxis;
      var yAxis;
      injectCoordSysByOption({
        targetModel: seriesModel,
        coordSysType: COORD_SYS_TYPE_CARTESIAN_2D,
        coordSysProvider: coordSysProvider
      });
      function coordSysProvider() {
        var axesModelMap = findAxisModels(seriesModel);
        var xAxisModel = axesModelMap.xAxisModel;
        var yAxisModel = axesModelMap.yAxisModel;
        xAxis = xAxisModel.axis;
        yAxis = yAxisModel.axis;
        var gridModel = xAxisModel.getCoordSysModel();
        if (process.env.NODE_ENV !== 'production') {
          if (!gridModel) {
            throw new Error('Grid "' + retrieve3(xAxisModel.get('gridIndex'), xAxisModel.get('gridId'), 0) + '" not found');
          }
          if (xAxisModel.getCoordSysModel() !== yAxisModel.getCoordSysModel()) {
            throw new Error('xAxis and yAxis must use the same grid');
          }
        }
        var grid = gridModel.coordinateSystem;
        return grid.getCartesian(xAxisModel.componentIndex, yAxisModel.componentIndex);
      }
      if (xAxis && yAxis) {
        associateSeriesWithAxis(xAxis, seriesModel, COORD_SYS_TYPE_CARTESIAN_2D);
        associateSeriesWithAxis(yAxis, seriesModel, COORD_SYS_TYPE_CARTESIAN_2D);
      }
    }, this);
    return grids;
  };
  // For deciding which dimensions to use when creating list data
  Grid.dimensions = cartesian2DDimensions;
  Grid.dimIdxMap = createDimNameMap(cartesian2DDimensions);
  return Grid;
}();
/**
 * Check if the axis is used in the specified grid.
 */
function isAxisUsedInTheGrid(axisModel, gridModel) {
  return axisModel.getCoordSysModel() === gridModel;
}
function fixAxisOnZero(axesMap, otherAxisDim, axis,
// Key: see `getOnZeroRecordKey`
onZeroRecords) {
  axis.getAxesOnZeroOf = function () {
    // TODO: onZero of multiple axes.
    return otherAxisOnZeroOf ? [otherAxisOnZeroOf] : [];
  };
  // onZero can not be enabled in these two situations:
  // 1. When any other axis is a category axis.
  // 2. When no axis is cross 0 point.
  var otherAxes = axesMap[otherAxisDim];
  var otherAxisOnZeroOf;
  var axisModel = axis.model;
  var onZero = axisModel.get(['axisLine', 'onZero']);
  var onZeroAxisIndex = axisModel.get(['axisLine', 'onZeroAxisIndex']);
  // For historical reason, ec option `axisLine.onZero: undefined` leads to "not on zero"
  // while leaving `axisLine.onZero` unspecified causes "on zero". This inconsistency goes
  // against common sense, but is preserved for backward compatibility.
  if (!onZero) {
    return;
  }
  // If target axis is specified.
  if (onZeroAxisIndex != null) {
    if (canOnZeroToAxis(onZero, otherAxes[onZeroAxisIndex])) {
      otherAxisOnZeroOf = otherAxes[onZeroAxisIndex];
    }
  } else {
    // Find the first available other axis.
    for (var idx in otherAxes) {
      if (hasOwn(otherAxes, idx) && canOnZeroToAxis(onZero, otherAxes[idx])
      // Consider that two Y axes on one value axis,
      // if both onZero, the two Y axes overlap.
      && !onZeroRecords[getOnZeroRecordKey(otherAxes[idx])]) {
        otherAxisOnZeroOf = otherAxes[idx];
        break;
      }
    }
  }
  if (otherAxisOnZeroOf) {
    onZeroRecords[getOnZeroRecordKey(otherAxisOnZeroOf)] = true;
  }
  function getOnZeroRecordKey(axis) {
    return axis.dim + '_' + axis.index;
  }
}
/**
 * CAVEAT: Must not be called before `CoordinateSystem#update` due to `__dontOnMyZero`.
 */
function canOnZeroToAxis(onZeroOption, axis) {
  if (!axis) {
    return false;
  }
  var scale = axis.scale;
  var kindEffective = getScaleValuePositionKind(scale, 0, false);
  var can = axis
  // PENDING: Historical behavior: `onZero` on 'category' and 'time' axis are always disabled
  // even if ec option gives `onZero: true`.
  && axis.type !== 'category' && axis.type !== 'time'
  // NOTE: Although the portion out of "effective" portion may also cross zero
  // (see `SCALE_EXTENT_KIND_MAPPING`), that is commonly meaningless, so we use
  // `SCALE_EXTENT_KIND_EFFECTIVE`
  && kindEffective !== SCALE_VALUE_POSITION_KIND_OUTSIDE;
  if (can && onZeroOption === 'auto'
  // Historically, "value" axis and "log" axis has been using `onZero: true` as the default.
  // It suitable for mathematic cases, even when dataZoom exists (e.g., `clip.html`), or cases
  // need to distinguish positive and negative data. However, it probably causes odd effect if
  // a "value axis" is laid on zero of a "base axis" in bar/candlestick, where the axis line
  // would likely cross shapes when `SCALE_EXTENT_KIND_MAPPING` is applied.
  // Therefore, we preserve backward compatibility of the default `onZero: true`, but exclude
  // cases that `containShape` is applied.
  && isOnAxisZeroDiscouraged(axis)
  // || (
  //     // Avoid axis line cross series shape (typically, bar series on "value"/"time" axis) unexpectedly.
  //     kindEffective === SCALE_VALUE_POSITION_KIND_EDGE
  //     && getScaleValuePositionKind(scale, 0, true) === SCALE_VALUE_POSITION_KIND_INSIDE
  // )
  ) {
    can = false;
  }
  // falsy value of `onZeroOption` has been handled in the previous logic.
  return can;
}
/**
 * [CAVEAT] This method is called before data processing stage.
 *  Do not rely on any info that is determined afterward.
 */
function prepareAlignToInCoordSysCreate(axes) {
  // Axis is added in order of axisIndex.
  var axesIndices = keys(axes);
  var alignTo;
  var axisNeedsAlign = [];
  for (var i = axesIndices.length - 1; i >= 0; i--) {
    // Reverse order
    var axis = axes[+axesIndices[i]];
    if (isIntervalOrLogScale(axis.scale)
    // NOTE: `scale.hasBreaks()` is not available at this moment. Check it later.
    && retrieveAxisBreaksOption(axis.model, axis.type, true) == null
    // NOTE: `scale.getTicks()` is not available at this moment. Check it later.
    ) {
      // Request `alignTicks`.
      if (axis.model.get('alignTicks') && axis.model.get('interval') == null) {
        axisNeedsAlign.push(axis);
      } else {
        // `alignTo` the last one that does not request `alignTicks`
        // (This rule is retained for backward compat).
        alignTo = axis;
      }
    }
  }
  ;
  // If all axes has set alignTicks, pick the first one as alignTo.
  // PENDING. Should we find the axis that both set interval, min, max and align to this one?
  // PENDING. Should we allow specifying alignTo via ec option?
  if (!alignTo) {
    alignTo = axisNeedsAlign.pop();
  }
  if (alignTo) {
    each(axisNeedsAlign, function (axis) {
      axis.__alignTo = alignTo;
    });
  }
}
/**
 * This is just a defence code. They are unlikely to be actually `true`,
 * since these cases have been addressed in `prepareAlignToInCoordSysCreate`.
 *
 * Can not be called BEFORE "nice" performed.
 */
function incapableOfAlignNeedFallback(targetAxis, alignTo) {
  return hasBreaks(targetAxis.scale) || hasBreaks(alignTo.scale)
  // Normally ticks length are more than 2 even when axis is blank.
  // But still guard for corner cases and possible changes.
  || alignTo.scale.getTicks().length < 2;
}
function updateAxisTransform(axis, coordBase) {
  var axisExtent = axis.getExtent();
  var axisExtentSum = axisExtent[0] + axisExtent[1];
  // Fast transform
  axis.toGlobalCoord = axis.dim === 'x' ? function (coord) {
    return coord + coordBase;
  } : function (coord) {
    return axisExtentSum - coord + coordBase;
  };
  axis.toLocalCoord = axis.dim === 'x' ? function (coord) {
    return coord - coordBase;
  } : function (coord) {
    return axisExtentSum - coord + coordBase;
  };
}
function updateAllAxisExtentTransByGridRect(axesMap, gridRect) {
  each(axesMap.x, function (axis) {
    return updateAxisExtentTransByGridRect(axis, gridRect.x, gridRect.width);
  });
  each(axesMap.y, function (axis) {
    return updateAxisExtentTransByGridRect(axis, gridRect.y, gridRect.height);
  });
}
function updateAxisExtentTransByGridRect(axis, gridXY, gridWH) {
  var extent = [0, gridWH];
  var idx = axis.inverse ? 1 : 0;
  axis.setExtent(extent[idx], extent[1 - idx]);
  updateAxisTransform(axis, gridXY);
}
var legacyLayOutGridByContainLabel;
export function registerLegacyGridContainLabelImpl(impl) {
  legacyLayOutGridByContainLabel = impl;
}
// Return noPxChange.
function layOutGridByOuterBounds(outerBoundsRect, outerBoundsContain, outerBoundsClamp, gridRect, axesMap, axisBuilderSharedCtx, layoutRef) {
  if (process.env.NODE_ENV !== 'production') {
    assert(outerBoundsContain === 'all' || outerBoundsContain === 'axisLabel');
  }
  // Assume `updateAllAxisExtentTransByGridRect` has been performed once before this call.
  // [NOTE]:
  // - The bounding rect of the axis elements might be sensitve to variations in `axis.extent` due to strategies
  //  like hideOverlap/moveOverlap. @see the comment in `LabelLayoutBase['suggestIgnore']`.
  // - The final `gridRect` might be slightly smaller than the ideally expected result if labels are giant and
  //  get hidden due to overlapping. More iterations could improve precision, but not performant. We consider
  //  the current result acceptable, since no alignment among charts can be guaranteed when using this feature.
  createOrUpdateAxesView(gridRect, axesMap, AxisTickLabelComputingKind.estimate, outerBoundsContain, false, layoutRef);
  var margin = [0, 0, 0, 0];
  fillLabelNameOverflowOnOneDimension(0);
  fillLabelNameOverflowOnOneDimension(1);
  // If axis is blank, no label can be used to detect overflow.
  // gridRect itself should not overflow.
  fillMarginOnOneDimension(gridRect, 0, NaN);
  fillMarginOnOneDimension(gridRect, 1, NaN);
  var noPxChange = find(margin, function (item) {
    return item > 0;
  }) == null;
  expandOrShrinkRect(gridRect, margin, true, true, outerBoundsClamp);
  updateAllAxisExtentTransByGridRect(axesMap, gridRect);
  return noPxChange;
  function fillLabelNameOverflowOnOneDimension(xyIdx) {
    each(axesMap[XY[xyIdx]], function (axis) {
      if (!shouldAxisShow(axis.model)) {
        return;
      }
      // FIXME: zr Group.union may wrongly union (0, 0, 0, 0) and not performant.
      // unionRect.union(axis.axisBuilder.group.getBoundingRect());
      // If ussing Group.getBoundingRect to calculate shrink space, it is not strictly accurate when
      // the outermost label is ignored and the secondary label is very long and contribute to the
      // union extension:
      //      -|---|---|---|
      //         1,000,000,000
      // Therefore we calculate them one by one.
      // Also considered axis may be blank or no labels.
      var sharedRecord = axisBuilderSharedCtx.ensureRecord(axis.model);
      var labelInfoList = sharedRecord.labelInfoList;
      if (labelInfoList) {
        for (var idx = 0; idx < labelInfoList.length; idx++) {
          var labelInfo = labelInfoList[idx];
          var proportion = axis.scale.normalize(getTickValueOutermost(axis.scale, getLabelInner(labelInfo.label).labelInfo.tick));
          proportion = xyIdx === 1 ? 1 - proportion : proportion;
          // xAxis use proportion on x, yAxis use proprotion on y, otherwise not.
          fillMarginOnOneDimension(labelInfo.rect, xyIdx, proportion);
          fillMarginOnOneDimension(labelInfo.rect, 1 - xyIdx, NaN);
        }
      }
      var nameLayout = sharedRecord.nameLayout;
      if (nameLayout) {
        var proportion = isNameLocationCenter(sharedRecord.nameLocation) ? 0.5 : NaN;
        fillMarginOnOneDimension(nameLayout.rect, xyIdx, proportion);
        fillMarginOnOneDimension(nameLayout.rect, 1 - xyIdx, NaN);
      }
    });
  }
  function fillMarginOnOneDimension(itemRect, xyIdx, proportion // NaN mean no use proportion
  ) {
    var overflow1 = outerBoundsRect[XY[xyIdx]] - itemRect[XY[xyIdx]];
    var overflow2 = itemRect[WH[xyIdx]] + itemRect[XY[xyIdx]] - (outerBoundsRect[WH[xyIdx]] + outerBoundsRect[XY[xyIdx]]);
    overflow1 = applyProportion(overflow1, 1 - proportion);
    overflow2 = applyProportion(overflow2, proportion);
    var minIdx = XY_TO_MARGIN_IDX[xyIdx][0];
    var maxIdx = XY_TO_MARGIN_IDX[xyIdx][1];
    margin[minIdx] = mathMax(margin[minIdx], overflow1);
    margin[maxIdx] = mathMax(margin[maxIdx], overflow2);
  }
  function applyProportion(overflow, proportion) {
    // proportion is not likely to near zero. If so, give up shrink
    if (overflow > 0 && !eqNaN(proportion) && proportion > 1e-4) {
      overflow /= proportion;
    }
    return overflow;
  }
}
function createAxisBiulders(gridRect, cartesians, axesMap, optionContainLabel, api) {
  var axisBuilderSharedCtx = new AxisBuilderSharedContext(resolveAxisNameOverlapForGrid);
  each(axesMap, function (axisList) {
    return each(axisList, function (axis) {
      if (shouldAxisShow(axis.model)) {
        // See `AxisBaseOptionCommon['nameMoveOverlap']`.
        var defaultNameMoveOverlap = !optionContainLabel;
        axis.axisBuilder = createCartesianAxisViewCommonPartBuilder(gridRect, cartesians, axis.model, api, axisBuilderSharedCtx, defaultNameMoveOverlap);
      }
    });
  });
  return axisBuilderSharedCtx;
}
/**
 * Promote the axis-elements-building from "view render" stage to "coordinate system resize" stage.
 * This is aimed to resovle overlap across multiple axes, since currently it's hard to reconcile
 * multiple axes in "view render" stage.
 *
 * [CAUTION] But this promotion assumes that the subsequent "visual mapping" stage does not affect
 * this axis-elements-building; otherwise we have to refactor it again.
 */
function createOrUpdateAxesView(gridRect, axesMap, kind, outerBoundsContain, noPxChange, layoutRef) {
  var isDetermine = kind === AxisTickLabelComputingKind.determine;
  each(axesMap, function (axisList) {
    return each(axisList, function (axis) {
      if (shouldAxisShow(axis.model)) {
        updateCartesianAxisViewCommonPartBuilder(axis.axisBuilder, gridRect, axis.model);
        axis.axisBuilder.build(isDetermine ? {
          axisTickLabelDetermine: true
        } : {
          axisTickLabelEstimate: true
        }, {
          noPxChange: noPxChange
        });
      }
    });
  });
  var nameMarginLevelMap = {
    x: 0,
    y: 0
  };
  calcNameMarginLevel(0);
  calcNameMarginLevel(1);
  function calcNameMarginLevel(xyIdx) {
    nameMarginLevelMap[XY[1 - xyIdx]] = gridRect[WH[xyIdx]] <= layoutRef.refContainer[WH[xyIdx]] * 0.5 ? 0 : 1 - xyIdx === 1 ? 2 : 1;
  }
  each(axesMap, function (axisList, xy) {
    return each(axisList, function (axis) {
      if (shouldAxisShow(axis.model)) {
        if (outerBoundsContain === 'all' || isDetermine) {
          // To resolve overlap, `axisName` layout depends on `axisTickLabel` layout result
          // (all of the axes of the same `grid`; consider multiple x or y axes).
          axis.axisBuilder.build({
            axisName: true
          }, {
            nameMarginLevel: nameMarginLevelMap[xy]
          });
        }
        if (isDetermine) {
          axis.axisBuilder.build({
            axisLine: true
          });
        }
      }
    });
  });
}
function prepareOuterBounds(gridModel, rawGridRect, layoutRef) {
  var outerBoundsRect;
  var optionOuterBoundsMode = gridModel.get('outerBoundsMode', true);
  if (optionOuterBoundsMode === 'same') {
    outerBoundsRect = rawGridRect.clone();
  } else if (optionOuterBoundsMode == null || optionOuterBoundsMode === 'auto') {
    outerBoundsRect = getLayoutRect(gridModel.get('outerBounds', true) || OUTER_BOUNDS_DEFAULT, layoutRef.refContainer);
  } else if (optionOuterBoundsMode !== 'none') {
    if (process.env.NODE_ENV !== 'production') {
      error("Invalid grid[" + gridModel.componentIndex + "].outerBoundsMode.");
    }
  }
  var optionOuterBoundsContain = gridModel.get('outerBoundsContain', true);
  var parsedOuterBoundsContain;
  if (optionOuterBoundsContain == null || optionOuterBoundsContain === 'auto') {
    parsedOuterBoundsContain = 'all';
  } else if (indexOf(['all', 'axisLabel'], optionOuterBoundsContain) < 0) {
    if (process.env.NODE_ENV !== 'production') {
      error("Invalid grid[" + gridModel.componentIndex + "].outerBoundsContain.");
    }
    parsedOuterBoundsContain = 'all';
  } else {
    parsedOuterBoundsContain = optionOuterBoundsContain;
  }
  var outerBoundsClamp = [parsePositionSizeOption(retrieve2(gridModel.get('outerBoundsClampWidth', true), OUTER_BOUNDS_CLAMP_DEFAULT[0]), rawGridRect.width), parsePositionSizeOption(retrieve2(gridModel.get('outerBoundsClampHeight', true), OUTER_BOUNDS_CLAMP_DEFAULT[1]), rawGridRect.height)];
  return {
    outerBoundsRect: outerBoundsRect,
    parsedOuterBoundsContain: parsedOuterBoundsContain,
    outerBoundsClamp: outerBoundsClamp
  };
}
var resolveAxisNameOverlapForGrid = function (cfg, ctx, axisModel, nameLayoutInfo, nameMoveDirVec, thisRecord) {
  var perpendicularDim = axisModel.axis.dim === 'x' ? 'y' : 'x';
  resolveAxisNameOverlapDefault(cfg, ctx, axisModel, nameLayoutInfo, nameMoveDirVec, thisRecord);
  // If nameLocation 'center', and there are multiple axes parallel to this axis, do not adjust by
  //  other axes, because the axis name should be close to its axis line as much as possible even
  //  if overlapping; otherwise it might cause misleading.
  // If nameLocation 'center', do not adjust by perpendicular axes, since they are not likely to overlap.
  // If nameLocation 'start'/'end', move name within the same direction to escape overlap with the
  //  perpendicular axes.
  if (!isNameLocationCenter(cfg.nameLocation)) {
    each(ctx.recordMap[perpendicularDim], function (perpenRecord) {
      // perpendicular axis may be no name.
      if (perpenRecord && perpenRecord.labelInfoList && perpenRecord.dirVec) {
        moveIfOverlapByLinearLabels(perpenRecord.labelInfoList, perpenRecord.dirVec, nameLayoutInfo, nameMoveDirVec);
      }
    });
  }
};
export default Grid;