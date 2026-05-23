
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
import { each, isString } from 'zrender/lib/core/util.js';
import { isSeriesDataSchema } from './SeriesDataSchema.js';
/**
 * Note that it is too complicated to support 3d stack by value
 * (have to create two-dimension inverted index), so in 3d case
 * we just support that stacked by index.
 *
 * Stack is calculated in `src/processor/dataStack.ts`.
 *
 * @param seriesModel
 * @param dimensionsInput The same as the input of <module:echarts/data/SeriesData>.
 *        The input will be modified.
 * @param opt
 * @param opt.stackedCoordDimension Specify a coord dimension if needed.
 * @param opt.byIndex=false
 * @return calculationInfo
 * {
 *     stackedDimension: string
 *     stackedByDimension: string
 *     isStackedByIndex: boolean
 *     stackedOverDimension: string
 *     stackResultDimension: string
 * }
 */
export function enableDataStack(seriesModel, dimensionsInput, opt) {
  opt = opt || {};
  var byIndex = opt.byIndex;
  var stackedCoordDimension = opt.stackedCoordDimension;
  var dimensionDefineList;
  var schema;
  var store;
  if (isLegacyDimensionsInput(dimensionsInput)) {
    dimensionDefineList = dimensionsInput;
  } else {
    schema = dimensionsInput.schema;
    dimensionDefineList = schema.dimensions;
    store = dimensionsInput.store;
  }
  // compatible: when `stack` is set as '', do not stack.
  var mayStack = !!(seriesModel && seriesModel.get('stack'));
  var stackedByDimInfo;
  var stackedDimInfo;
  var stackResultDimension;
  var stackedOverDimension;
  var allDimTypesAreNotOrdinalAndTime = true;
  function dimTypeIsNotOrdinalAndTime(dimensionInfo) {
    return dimensionInfo.type !== 'ordinal' && dimensionInfo.type !== 'time';
  }
  each(dimensionDefineList, function (dimensionInfo, index) {
    if (isString(dimensionInfo)) {
      dimensionDefineList[index] = dimensionInfo = {
        name: dimensionInfo
      };
    }
    if (!dimTypeIsNotOrdinalAndTime(dimensionInfo)) {
      allDimTypesAreNotOrdinalAndTime = false;
    }
  });
  each(dimensionDefineList, function (dimensionInfo, index) {
    if (mayStack && !dimensionInfo.isExtraCoord) {
      // Find the first ordinal dimension as the stackedByDimInfo.
      if (!byIndex && !stackedByDimInfo && dimensionInfo.ordinalMeta) {
        stackedByDimInfo = dimensionInfo;
      }
      // Find the first stackable dimension as the stackedDimInfo.
      if (!stackedDimInfo && dimTypeIsNotOrdinalAndTime(dimensionInfo)
      // FIXME:
      //  This rule MUST be consistent with `Cartesian2D['getBaseAxis']` and `Polar['getBaseAxis']`
      //  Need refactor - merge them!
      //  See comments in `Cartesian2D['getBaseAxis']` for details.
      && (!allDimTypesAreNotOrdinalAndTime || dimensionInfo.coordDim !== 'x' && dimensionInfo.coordDim !== 'angle') && (!stackedCoordDimension || stackedCoordDimension === dimensionInfo.coordDim)) {
        stackedDimInfo = dimensionInfo;
      }
    }
  });
  if (stackedDimInfo && !byIndex && !stackedByDimInfo) {
    // "Stack by data index" makes sense only if users provide carefully constructed data - any
    // mismatch or absence of data items can cause incorrect results. By "Stack by data index"
    // is more performant - no hashmap is required.
    // PENDING:
    //  Compatible with previous design, non-category axis ("value"/"log"/"time" axis) can only
    //  stack by index. "Stack by value" will not be supported until concrete requirements arise.
    byIndex = true;
  }
  if (stackedDimInfo) {
    // Use a weird name that not duplicated with other names.
    // Also need to use seriesModel.id as postfix because different
    // series may share same data store. The stack dimension needs to be distinguished.
    stackResultDimension = '__\0ecstackresult_' + seriesModel.id;
    stackedOverDimension = '__\0ecstackedover_' + seriesModel.id;
    // Create inverted index to fast query index by value.
    if (stackedByDimInfo) {
      stackedByDimInfo.createInvertedIndices = true;
    }
    var stackedDimCoordDim_1 = stackedDimInfo.coordDim;
    var stackedDimType = stackedDimInfo.type;
    var stackedDimCoordIndex_1 = 0;
    each(dimensionDefineList, function (dimensionInfo) {
      if (dimensionInfo.coordDim === stackedDimCoordDim_1) {
        stackedDimCoordIndex_1++;
      }
    });
    var stackedOverDimensionDefine = {
      name: stackResultDimension,
      coordDim: stackedDimCoordDim_1,
      coordDimIndex: stackedDimCoordIndex_1,
      type: stackedDimType,
      isExtraCoord: true,
      isCalculationCoord: true,
      storeDimIndex: dimensionDefineList.length
    };
    var stackResultDimensionDefine = {
      name: stackedOverDimension,
      // This dimension contains stack base (generally, 0), so do not set it as
      // `stackedDimCoordDim` to avoid extent calculation, consider log scale.
      coordDim: stackedOverDimension,
      coordDimIndex: stackedDimCoordIndex_1 + 1,
      type: stackedDimType,
      isExtraCoord: true,
      isCalculationCoord: true,
      storeDimIndex: dimensionDefineList.length + 1
    };
    if (schema) {
      if (store) {
        stackedOverDimensionDefine.storeDimIndex = store.ensureCalculationDimension(stackedOverDimension, stackedDimType);
        stackResultDimensionDefine.storeDimIndex = store.ensureCalculationDimension(stackResultDimension, stackedDimType);
      }
      schema.appendCalculationDimension(stackedOverDimensionDefine);
      schema.appendCalculationDimension(stackResultDimensionDefine);
    } else {
      dimensionDefineList.push(stackedOverDimensionDefine);
      dimensionDefineList.push(stackResultDimensionDefine);
    }
  }
  return {
    stackedDimension: stackedDimInfo && stackedDimInfo.name,
    stackedByDimension: stackedByDimInfo && stackedByDimInfo.name,
    isStackedByIndex: byIndex,
    stackedOverDimension: stackedOverDimension,
    stackResultDimension: stackResultDimension
  };
}
function isLegacyDimensionsInput(dimensionsInput) {
  return !isSeriesDataSchema(dimensionsInput.schema);
}
export function isDimensionStacked(data, stackedDim) {
  // Each single series only maps to one pair of axis. So we do not need to
  // check stackByDim, whatever stacked by a dimension or stacked by index.
  return !!stackedDim && stackedDim === data.getCalculationInfo('stackedDimension');
}
export function getStackedDimension(data, targetDim) {
  return isDimensionStacked(data, targetDim) ? data.getCalculationInfo('stackResultDimension') : targetDim;
}