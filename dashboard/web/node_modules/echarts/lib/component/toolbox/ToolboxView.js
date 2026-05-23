
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
import * as textContain from 'zrender/lib/contain/text.js';
import * as graphic from '../../util/graphic.js';
import { enterEmphasis, leaveEmphasis } from '../../util/states.js';
import Model from '../../model/Model.js';
import DataDiffer from '../../data/DataDiffer.js';
import * as listComponentHelper from '../helper/listComponent.js';
import ComponentView from '../../view/Component.js';
import { ToolboxFeature, getFeature } from './featureManager.js';
import { getUID } from '../../util/component.js';
import ZRText from 'zrender/lib/graphic/Text.js';
import { getFont } from '../../label/labelStyle.js';
import { box, createBoxLayoutReference, getLayoutRect, positionElement } from '../../util/layout.js';
import tokens from '../../visual/tokens.js';
import { bind, createHashMap, curry, each, filter, isFunction, isString } from 'zrender/lib/core/util.js';
var ToolboxView = /** @class */function (_super) {
  __extends(ToolboxView, _super);
  function ToolboxView() {
    return _super !== null && _super.apply(this, arguments) || this;
  }
  ToolboxView.prototype.render = function (toolboxModel, ecModel, api, payload) {
    var group = this.group;
    group.removeAll();
    if (!toolboxModel.get('show')) {
      return;
    }
    var itemSize = +toolboxModel.get('itemSize');
    var isVertical = toolboxModel.get('orient') === 'vertical';
    var featureOpts = toolboxModel.get('feature') || {};
    var features = this._features || (this._features = createHashMap());
    var newFeatureNames = []; // Includes both `show: true/false`.
    each(featureOpts, function (opt, name) {
      newFeatureNames.push(name);
    });
    // Diff by feature name.
    new DataDiffer(this._featureNames || [], newFeatureNames).add(processFeature).update(processFeature).remove(curry(processFeature, null)).execute();
    // Keep for diff.
    this._featureNames = filter(newFeatureNames, function (name) {
      return features.hasKey(name);
    });
    function processFeature(newIndex, oldIndex) {
      var isDiffAdd = newIndex != null && oldIndex == null;
      var isDiffUpdate = newIndex != null && oldIndex != null;
      var isDiffRemove = newIndex == null;
      var featureName = isDiffAdd || isDiffUpdate ? newFeatureNames[newIndex] : newFeatureNames[oldIndex];
      var featureOpt = featureOpts[featureName];
      var featureModel = isDiffAdd || isDiffUpdate ? new Model(featureOpt, toolboxModel, ecModel) : null;
      // `.get('show')` Also considered UserDefinedToolboxFeature
      var isFeatureShow = featureModel && featureModel.get('show');
      var feature;
      if (isDiffAdd) {
        // DIFF_ADD
        if (!isFeatureShow) {
          return;
        }
        if (isUserFeatureName(featureName)) {
          feature = {
            onclick: featureModel.option.onclick,
            featureName: featureName
          };
        } else {
          var Feature = getFeature(featureName);
          if (!Feature) {
            return;
          }
          feature = new Feature();
        }
        features.set(featureName, feature);
      } else {
        // DIFF_UPDATE or DIFF_REMOVE
        feature = features.get(featureName);
      }
      if (isDiffRemove || !isFeatureShow) {
        if (isTooltipFeature(feature) && feature.dispose) {
          feature.dispose(ecModel, api);
        }
        features.removeKey(featureName);
        return;
      }
      // FIX#11236, merge feature title from MagicType newOption. TODO: consider seriesIndex ?
      if (payload && payload.newTitle != null && payload.featureName === featureName) {
        // FIXME: ec option should not be modified here.
        featureOpt.title = payload.newTitle;
      }
      if (isDiffAdd) {
        feature.uid = getUID('toolbox-feature');
      }
      feature.model = featureModel;
      feature.ecModel = ecModel;
      feature.api = api;
      createIconPaths(featureModel, feature, featureName);
      featureModel.setIconStatus = function (iconName, status) {
        var option = this.option;
        var iconPaths = this.iconPaths;
        option.iconStatus = option.iconStatus || {};
        option.iconStatus[iconName] = status;
        if (iconPaths[iconName]) {
          (status === 'emphasis' ? enterEmphasis : leaveEmphasis)(iconPaths[iconName]);
        }
      };
      if (isTooltipFeature(feature) && feature.render) {
        feature.render(featureModel, ecModel, api, payload);
      }
    }
    function createIconPaths(featureModel, feature, featureName) {
      var iconStyleModel = featureModel.getModel('iconStyle');
      var iconStyleEmphasisModel = featureModel.getModel(['emphasis', 'iconStyle']);
      // If one feature has multiple icons, they are organized as
      // {
      //     icon: {
      //         foo: '',
      //         bar: ''
      //     },
      //     title: {
      //         foo: '',
      //         bar: ''
      //     }
      // }
      var icons = feature instanceof ToolboxFeature && feature.getIcons ? feature.getIcons() : featureModel.get('icon');
      var titles = featureModel.get('title') || {};
      var iconsMap;
      var titlesMap;
      if (isString(icons)) {
        iconsMap = {};
        iconsMap[featureName] = icons;
      } else {
        iconsMap = icons;
      }
      if (isString(titles)) {
        titlesMap = {};
        titlesMap[featureName] = titles;
      } else {
        titlesMap = titles;
      }
      var iconPaths = featureModel.iconPaths = {};
      each(iconsMap, function (iconStr, iconName) {
        var path = graphic.createIcon(iconStr, {}, {
          x: -itemSize / 2,
          y: -itemSize / 2,
          width: itemSize,
          height: itemSize
        }); // TODO handling image
        path.setStyle(iconStyleModel.getItemStyle());
        var pathEmphasisState = path.ensureState('emphasis');
        pathEmphasisState.style = iconStyleEmphasisModel.getItemStyle();
        // Text position calculation
        // TODO: extract `textStyle` from `iconStyle` and use `createTextStyle`
        var textContent = new ZRText({
          style: {
            text: titlesMap[iconName],
            align: iconStyleEmphasisModel.get('textAlign'),
            borderRadius: iconStyleEmphasisModel.get('textBorderRadius'),
            padding: iconStyleEmphasisModel.get('textPadding'),
            fill: null,
            font: getFont({
              fontStyle: iconStyleEmphasisModel.get('textFontStyle'),
              fontFamily: iconStyleEmphasisModel.get('textFontFamily'),
              fontSize: iconStyleEmphasisModel.get('textFontSize'),
              fontWeight: iconStyleEmphasisModel.get('textFontWeight')
            }, ecModel)
          },
          ignore: true
        });
        path.setTextContent(textContent);
        graphic.setTooltipConfig({
          el: path,
          componentModel: toolboxModel,
          itemName: iconName,
          formatterParamsExtra: {
            title: titlesMap[iconName]
          }
        });
        path.__title = titlesMap[iconName];
        path.on('mouseover', function () {
          // Should not reuse above hoverStyle, which might be modified.
          var hoverStyle = iconStyleEmphasisModel.getItemStyle();
          var defaultTextPosition = isVertical ? toolboxModel.get('right') == null && toolboxModel.get('left') !== 'right' ? 'right' : 'left' : toolboxModel.get('bottom') == null && toolboxModel.get('top') !== 'bottom' ? 'bottom' : 'top';
          textContent.setStyle({
            fill: iconStyleEmphasisModel.get('textFill') || hoverStyle.fill || hoverStyle.stroke || tokens.color.neutral99,
            backgroundColor: iconStyleEmphasisModel.get('textBackgroundColor')
          });
          path.setTextConfig({
            position: iconStyleEmphasisModel.get('textPosition') || defaultTextPosition
          });
          textContent.ignore = !toolboxModel.get('showTitle');
          // Use enterEmphasis and leaveEmphasis provide by ec.
          // There are flags managed by the echarts.
          api.enterEmphasis(this);
        }).on('mouseout', function () {
          if (featureModel.get(['iconStatus', iconName]) !== 'emphasis') {
            api.leaveEmphasis(this);
          }
          textContent.hide();
        });
        (featureModel.get(['iconStatus', iconName]) === 'emphasis' ? enterEmphasis : leaveEmphasis)(path);
        group.add(path);
        path.on('click', bind(feature.onclick, feature, ecModel, api, iconName));
        iconPaths[iconName] = path;
      });
    }
    var refContainer = createBoxLayoutReference(toolboxModel, api).refContainer;
    var boxLayoutParams = toolboxModel.getBoxLayoutParams();
    var padding = toolboxModel.get('padding');
    var viewRect = getLayoutRect(boxLayoutParams, refContainer, padding);
    box(toolboxModel.get('orient'), group, toolboxModel.get('itemGap'), viewRect.width, viewRect.height);
    positionElement(group, boxLayoutParams, refContainer, padding);
    // Render background after group is layout
    // FIXME
    group.add(listComponentHelper.makeBackground(group.getBoundingRect(), toolboxModel));
    // Adjust icon title positions to avoid them out of screen
    isVertical || group.eachChild(function (icon) {
      var titleText = icon.__title;
      // const hoverStyle = icon.hoverStyle;
      // TODO simplify code?
      var emphasisState = icon.ensureState('emphasis');
      var emphasisTextConfig = emphasisState.textConfig || (emphasisState.textConfig = {});
      var textContent = icon.getTextContent();
      var emphasisTextState = textContent && textContent.ensureState('emphasis');
      // May be background element
      if (emphasisTextState && !isFunction(emphasisTextState) && titleText) {
        var emphasisTextStyle = emphasisTextState.style || (emphasisTextState.style = {});
        var rect = textContain.getBoundingRect(titleText, ZRText.makeFont(emphasisTextStyle));
        var offsetX = icon.x + group.x;
        var offsetY = icon.y + group.y + itemSize;
        var needPutOnTop = false;
        if (offsetY + rect.height > api.getHeight()) {
          emphasisTextConfig.position = 'top';
          needPutOnTop = true;
        }
        var topOffset = needPutOnTop ? -5 - rect.height : itemSize + 10;
        if (offsetX + rect.width / 2 > api.getWidth()) {
          emphasisTextConfig.position = ['100%', topOffset];
          emphasisTextStyle.align = 'right';
        } else if (offsetX - rect.width / 2 < 0) {
          emphasisTextConfig.position = [0, topOffset];
          emphasisTextStyle.align = 'left';
        }
      }
    });
  };
  ToolboxView.prototype.updateView = function (toolboxModel, ecModel, api, payload) {
    each(this._features, function (feature) {
      feature && feature instanceof ToolboxFeature && feature.updateView && feature.updateView(feature.model, ecModel, api, payload);
    });
  };
  ToolboxView.prototype.dispose = function (ecModel, api) {
    each(this._features, function (feature) {
      feature && feature instanceof ToolboxFeature && feature.dispose && feature.dispose(ecModel, api);
    });
  };
  ToolboxView.type = 'toolbox';
  return ToolboxView;
}(ComponentView);
function isUserFeatureName(featureName) {
  return featureName.indexOf('my') === 0;
}
function isTooltipFeature(feature) {
  return feature instanceof ToolboxFeature;
}
export default ToolboxView;