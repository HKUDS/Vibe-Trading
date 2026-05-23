
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
import * as featureManager from './featureManager.js';
import ComponentModel from '../../model/Component.js';
import tokens from '../../visual/tokens.js';
import { each, extend, merge } from 'zrender/lib/core/util.js';
var ToolboxModel = /** @class */function (_super) {
  __extends(ToolboxModel, _super);
  function ToolboxModel() {
    var _this = _super !== null && _super.apply(this, arguments) || this;
    _this.type = ToolboxModel.type;
    return _this;
  }
  ToolboxModel.prototype.init = function (option, parentModel, ecModel) {
    // An historical behavior:
    //  An initial ec option
    //       chart.setOption( {toolbox: {feature: { featureA: {}, featureB: {}, }} } )
    //  indicates the declared toolbox features need to be enabled regardless of whether property
    //  "show" is explicity specified. But the subsequent `setOption` in merge mode requires property
    //  "show: false" to be explicity specified if intending to remove features, for example:
    //       chart.setOption( {toolbox: {feature: { featureA: {show: false}, featureC: {} } )
    // We keep backward compatibility and perform specific processing to prevent theme
    // settings from breaking it.
    var toolboxOptionInTheme = ecModel.getTheme().get('toolbox');
    var themeFeatureOption = toolboxOptionInTheme ? toolboxOptionInTheme.feature : null;
    if (themeFeatureOption) {
      // Use extend - the first level of the feature option will be modified later.
      this._themeFeatureOption = extend({}, themeFeatureOption);
      toolboxOptionInTheme.feature = {};
    }
    _super.prototype.init.call(this, option, parentModel, ecModel); // merge theme is performed inside it.
    if (themeFeatureOption) {
      toolboxOptionInTheme.feature = themeFeatureOption; // Recover
    }
  };
  ToolboxModel.prototype.optionUpdated = function () {
    each(this.option.feature, function (featureOpt, featureName) {
      var themeFeatureOption = this._themeFeatureOption;
      var Feature = featureManager.getFeature(featureName);
      if (Feature) {
        if (Feature.getDefaultOption) {
          Feature.defaultOption = Feature.getDefaultOption(this.ecModel);
        }
        if (themeFeatureOption && themeFeatureOption[featureName]) {
          merge(featureOpt, themeFeatureOption[featureName]);
          // Follow the previous behavior, theme is only be merged once.
          themeFeatureOption[featureName] = null;
        }
        merge(featureOpt, Feature.defaultOption);
      }
    }, this);
  };
  ToolboxModel.type = 'toolbox';
  ToolboxModel.layoutMode = {
    type: 'box',
    ignoreSize: true
  };
  ToolboxModel.defaultOption = {
    show: true,
    z: 6,
    // zlevel: 0,
    orient: 'horizontal',
    left: 'right',
    top: 'top',
    // right
    // bottom
    backgroundColor: 'transparent',
    borderColor: tokens.color.border,
    borderRadius: 0,
    borderWidth: 0,
    padding: tokens.size.m,
    itemSize: 15,
    itemGap: tokens.size.s,
    showTitle: true,
    iconStyle: {
      borderColor: tokens.color.accent50,
      color: 'none'
    },
    emphasis: {
      iconStyle: {
        borderColor: tokens.color.accent70
      }
    },
    // textStyle: {},
    // feature
    tooltip: {
      show: false,
      position: 'bottom'
    }
  };
  return ToolboxModel;
}(ComponentModel);
export default ToolboxModel;