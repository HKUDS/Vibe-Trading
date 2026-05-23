
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
import { __extends } from "tslib";
import * as zrUtil from 'zrender/lib/core/util.js';
import axisDefault from '../axisDefault.js';
import Model from '../../model/Model.js';
import { AxisModelCommonMixin } from '../axisModelCommonMixin.js';
import ComponentModel from '../../model/Component.js';
import tokens from '../../visual/tokens.js';
import { getUID } from '../../util/component.js';
var valueAxisDefault = axisDefault.value;
export var COORD_SYS_TYPE_RADAR = 'radar';
export var COMPONENT_TYPE_RADAR = COORD_SYS_TYPE_RADAR;
export var SERIES_TYPE_RADAR = COORD_SYS_TYPE_RADAR;
export var RADAR_DEFAULT_SPLIT_NUMBER = 5;
function defaultsShow(opt, show) {
  return zrUtil.defaults({
    show: show
  }, opt);
}
var RadarModel = /** @class */function (_super) {
  __extends(RadarModel, _super);
  function RadarModel() {
    var _this = _super !== null && _super.apply(this, arguments) || this;
    _this.type = RadarModel.type;
    return _this;
  }
  RadarModel.prototype.optionUpdated = function () {
    var boundaryGap = this.get('boundaryGap');
    var splitNumber = this.get('splitNumber');
    var clockwise = this.get('clockwise');
    var scale = this.get('scale');
    var axisLine = this.get('axisLine');
    var axisTick = this.get('axisTick');
    // let axisType = this.get('axisType');
    var axisLabel = this.get('axisLabel');
    var nameTextStyle = this.get('axisName');
    var showName = this.get(['axisName', 'show']);
    var nameFormatter = this.get(['axisName', 'formatter']);
    var nameGap = this.get('axisNameGap');
    var triggerEvent = this.get('triggerEvent');
    var indicatorModels = zrUtil.map(this.get('indicator') || [], function (indicatorOpt) {
      // PENDING
      if (indicatorOpt.max != null && indicatorOpt.max > 0 && !indicatorOpt.min) {
        indicatorOpt.min = 0;
      } else if (indicatorOpt.min != null && indicatorOpt.min < 0 && !indicatorOpt.max) {
        indicatorOpt.max = 0;
      }
      var iNameTextStyle = nameTextStyle;
      if (indicatorOpt.color != null) {
        iNameTextStyle = zrUtil.defaults({
          color: indicatorOpt.color
        }, nameTextStyle);
      }
      // Use same configuration
      var innerIndicatorOpt = zrUtil.merge(zrUtil.clone(indicatorOpt), {
        boundaryGap: boundaryGap,
        splitNumber: splitNumber,
        clockwise: clockwise,
        scale: scale,
        axisLine: axisLine,
        axisTick: axisTick,
        // axisType: axisType,
        axisLabel: axisLabel,
        // Compatible with 2 and use text
        name: indicatorOpt.text,
        showName: showName,
        nameLocation: 'end',
        nameGap: nameGap,
        // min: 0,
        nameTextStyle: iNameTextStyle,
        triggerEvent: triggerEvent
      }, false);
      if (zrUtil.isString(nameFormatter)) {
        var indName = innerIndicatorOpt.name;
        innerIndicatorOpt.name = nameFormatter.replace('{value}', indName != null ? indName : '');
      } else if (zrUtil.isFunction(nameFormatter)) {
        innerIndicatorOpt.name = nameFormatter(innerIndicatorOpt.name, innerIndicatorOpt);
      }
      var model = new Model(innerIndicatorOpt, null, this.ecModel);
      zrUtil.mixin(model, AxisModelCommonMixin.prototype);
      // For triggerEvent.
      model.mainType = 'radar';
      model.componentIndex = this.componentIndex;
      // FIXME: construct an AxisBaseModel directly, rather than mixin.
      // @ts-ignore
      model.uid = getUID('ec_radar');
      return model;
    }, this);
    this._indicatorModels = indicatorModels;
  };
  RadarModel.prototype.getIndicatorModels = function () {
    return this._indicatorModels;
  };
  RadarModel.type = COMPONENT_TYPE_RADAR;
  RadarModel.defaultOption = {
    // zlevel: 0,
    z: 0,
    center: ['50%', '50%'],
    radius: '50%',
    startAngle: 90,
    clockwise: false,
    axisName: {
      show: true,
      color: tokens.color.axisLabel
      // formatter: null
      // textStyle: {}
    },
    boundaryGap: [0, 0],
    splitNumber: RADAR_DEFAULT_SPLIT_NUMBER,
    axisNameGap: 15,
    scale: false,
    // Polygon or circle
    shape: 'polygon',
    axisLine: zrUtil.merge({
      lineStyle: {
        color: tokens.color.neutral20
      }
    }, valueAxisDefault.axisLine),
    axisLabel: defaultsShow(valueAxisDefault.axisLabel, false),
    axisTick: defaultsShow(valueAxisDefault.axisTick, false),
    // axisType: 'value',
    splitLine: defaultsShow(valueAxisDefault.splitLine, true),
    splitArea: defaultsShow(valueAxisDefault.splitArea, true),
    // {text, min, max}
    indicator: []
  };
  return RadarModel;
}(ComponentModel);
export default RadarModel;