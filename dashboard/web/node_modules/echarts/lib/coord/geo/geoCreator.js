
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
import Geo, { geo2DDimensions } from './Geo.js';
import * as layout from '../../util/layout.js';
import * as numberUtil from '../../util/number.js';
import geoSourceManager from './geoSourceManager.js';
import { buildAllMapSeriesGroups, mapSeriesGroupHasOwnGeo, SERIES_TYPE_MAP } from '../../chart/map/MapSeries.js';
import * as vector from 'zrender/lib/core/vector.js';
import { injectCoordSysByOption } from '../../core/CoordinateSystem.js';
import { SINGLE_REFERRING } from '../../util/model.js';
import { viewCoordSysSetBoundingRect, viewCoordSysSetRoamOptionFromModel, viewCoordSysSetViewRect } from '../View.js';
/**
 * Resize method bound to the geo
 */
function resizeGeo(geoModel, api) {
  var viewCoordSys = this.view;
  var boundingCoords = geoModel.get('boundingCoords');
  if (boundingCoords != null) {
    var leftTop_1 = boundingCoords[0];
    var rightBottom_1 = boundingCoords[1];
    if (!(isFinite(leftTop_1[0]) && isFinite(leftTop_1[1]) && isFinite(rightBottom_1[0]) && isFinite(rightBottom_1[1]))) {
      if (process.env.NODE_ENV !== 'production') {
        console.error('Invalid boundingCoords');
      }
    } else {
      // Sample around the lng/lat rect and use projection to calculate actual bounding rect.
      var projection_1 = this.projection;
      if (projection_1) {
        var xMin = leftTop_1[0];
        var yMin = leftTop_1[1];
        var xMax = rightBottom_1[0];
        var yMax = rightBottom_1[1];
        leftTop_1 = [Infinity, Infinity];
        rightBottom_1 = [-Infinity, -Infinity];
        // TODO better way?
        var sampleLine = function (x0, y0, x1, y1) {
          var dx = x1 - x0;
          var dy = y1 - y0;
          for (var i = 0; i <= 100; i++) {
            var p = i / 100;
            var pt = projection_1.project([x0 + dx * p, y0 + dy * p]);
            vector.min(leftTop_1, leftTop_1, pt);
            vector.max(rightBottom_1, rightBottom_1, pt);
          }
        };
        // Top
        sampleLine(xMin, yMin, xMax, yMin);
        // Right
        sampleLine(xMax, yMin, xMax, yMax);
        // Bottom
        sampleLine(xMax, yMax, xMin, yMax);
        // Left
        sampleLine(xMin, yMax, xMax, yMin);
      }
      viewCoordSysSetBoundingRect(viewCoordSys, leftTop_1[0], leftTop_1[1], rightBottom_1[0] - leftTop_1[0], rightBottom_1[1] - leftTop_1[1]);
    }
  }
  var rect = viewCoordSys.getBoundingRect();
  var centerOption = geoModel.get('layoutCenter');
  var sizeOption = geoModel.get('layoutSize');
  // Laying out geo on Cartesian works theoretically but not supported yet.
  // Currently, we only support to lay out on matrix/calendar.
  var refContainer = layout.createBoxLayoutReference(geoModel, api).refContainer;
  var aspect = rect.width / rect.height * this.aspectScale;
  var useCenterAndSize = false;
  var center;
  var size;
  if (centerOption && sizeOption) {
    center = [numberUtil.parsePercent(centerOption[0], refContainer.width) + refContainer.x, numberUtil.parsePercent(centerOption[1], refContainer.height) + refContainer.y];
    size = numberUtil.parsePercent(sizeOption, Math.min(refContainer.width, refContainer.height));
    if (!isNaN(center[0]) && !isNaN(center[1]) && !isNaN(size)) {
      useCenterAndSize = true;
    } else {
      if (process.env.NODE_ENV !== 'production') {
        console.warn('Given layoutCenter or layoutSize data are invalid. Use left/top/width/height instead.');
      }
    }
  }
  var viewRect;
  if (useCenterAndSize) {
    viewRect = {};
    if (aspect > 1) {
      // Width is same with size
      viewRect.width = size;
      viewRect.height = size / aspect;
    } else {
      viewRect.height = size;
      viewRect.width = size * aspect;
    }
    viewRect.y = center[1] - viewRect.height / 2;
    viewRect.x = center[0] - viewRect.width / 2;
  } else {
    // Use left/top/width/height
    var boxLayoutOption = geoModel.getBoxLayoutParams();
    boxLayoutOption.aspect = aspect;
    viewRect = layout.getLayoutRect(boxLayoutOption, refContainer);
    viewRect = layout.applyPreserveAspect(geoModel, viewRect, aspect);
  }
  viewCoordSysSetViewRect(viewCoordSys, viewRect.x, viewRect.y, viewRect.width, viewRect.height);
  viewCoordSysSetRoamOptionFromModel(viewCoordSys, geoModel);
}
// Back compat for ECharts2, where the coord map is set on map series:
// {type: 'map', geoCoord: {'cityA': [116.46,39.92], 'cityA': [119.12,24.61]}},
function setGeoCoords(geo, model) {
  zrUtil.each(model.get('geoCoord'), function (geoCoord, name) {
    geo.addGeoCoord(name, geoCoord);
  });
}
var GeoCreator = /** @class */function () {
  function GeoCreator() {
    // For deciding which dimensions to use when creating list data
    this.dimensions = geo2DDimensions;
  }
  GeoCreator.prototype.create = function (ecModel, api) {
    var geoList = [];
    function getCommonGeoProperties(model) {
      return {
        nameProperty: model.get('nameProperty'),
        aspectScale: model.get('aspectScale'),
        projection: model.get('projection'),
        clip: model.getShallow('clip', true)
      };
    }
    // FIXME Create each time may be slow
    ecModel.eachComponent('geo', function (geoModel, idx) {
      var mapName = geoModel.get('map');
      var geo = new Geo(mapName + idx, mapName, zrUtil.extend({
        nameMap: geoModel.get('nameMap'),
        api: api,
        ecModel: ecModel
      }, getCommonGeoProperties(geoModel)));
      geoList.push(geo);
      // setGeoCoords(geo, geoModel);
      geoModel.coordinateSystem = geo;
      geo.model = geoModel;
      // Inject resize method
      geo.resize = resizeGeo;
      geo.resize(geoModel, api);
    });
    ecModel.eachSeries(function (seriesModel) {
      injectCoordSysByOption({
        targetModel: seriesModel,
        coordSysType: 'geo',
        coordSysProvider: function () {
          var geoModel = seriesModel.subType === SERIES_TYPE_MAP ? seriesModel.getHostGeoModel() : seriesModel.getReferringComponents('geo', SINGLE_REFERRING).models[0];
          return geoModel && geoModel.coordinateSystem;
        },
        allowNotFound: true
      });
    });
    // If has map series
    zrUtil.each(buildAllMapSeriesGroups(ecModel, true), function (mapSeriesGroup, groupKey) {
      if (!mapSeriesGroupHasOwnGeo(groupKey)) {
        return;
      }
      var firstDeclaredMapSeries = mapSeriesGroup.r[0];
      var nameMapList = [];
      zrUtil.each(mapSeriesGroup.r, function (mapSeries) {
        nameMapList.push(mapSeries.get('nameMap'));
        // MAP_SERIES_GROUP must not be set here, as series filtering is not performed.
        // Clear it first, including series to be filtered.
        mapSeries.seriesGroup = null;
      });
      var mapType = groupKey.slice(1);
      var geo = new Geo(mapType, mapType, zrUtil.extend({
        nameMap: zrUtil.mergeAll(nameMapList),
        api: api,
        ecModel: ecModel
      }, getCommonGeoProperties(firstDeclaredMapSeries)));
      var scaleLimit;
      zrUtil.each(mapSeriesGroup.r, function (mapSeries) {
        scaleLimit = zrUtil.retrieve2(scaleLimit, mapSeries.get('scaleLimit'));
      });
      geoList.push(geo);
      // Inject resize method
      geo.resize = resizeGeo;
      geo.resize(firstDeclaredMapSeries, api);
      zrUtil.each(mapSeriesGroup.r, function (mapSeries) {
        mapSeries.coordinateSystem = geo;
        setGeoCoords(geo, mapSeries);
      });
    });
    return geoList;
  };
  /**
   * Fill given regions array
   */
  GeoCreator.prototype.getFilledRegions = function (originRegionArr, mapName, nameMap, nameProperty) {
    // Not use the original
    var regionsArr = (originRegionArr || []).slice();
    var dataNameMap = zrUtil.createHashMap();
    for (var i = 0; i < regionsArr.length; i++) {
      dataNameMap.set(regionsArr[i].name, regionsArr[i]);
    }
    var source = geoSourceManager.load(mapName, nameMap, nameProperty);
    zrUtil.each(source.regions, function (region) {
      var name = region.name;
      var regionOption = dataNameMap.get(name);
      // apply specified echarts style in GeoJSON data
      var specifiedGeoJSONRegionStyle = region.properties && region.properties.echartsStyle;
      if (!regionOption) {
        regionOption = {
          name: name
        };
        regionsArr.push(regionOption);
      }
      specifiedGeoJSONRegionStyle && zrUtil.merge(regionOption, specifiedGeoJSONRegionStyle);
    });
    return regionsArr;
  };
  return GeoCreator;
}();
var geoCreator = new GeoCreator();
export default geoCreator;