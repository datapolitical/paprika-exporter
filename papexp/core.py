#!/usr/bin/env python3

import json
import os
import shutil
from base64 import b64encode
from http.client import HTTPSConnection

import pathlib

import yaml

import requests
from dotenv import load_dotenv
load_dotenv()

email = os.environ['PAPRIKA_EMAIL']
password = os.environ['PAPRIKA_PASSWORD']

c = HTTPSConnection("www.paprikaapp.com")

userAndPass = b64encode(bytes(email+":"+password, 'utf-8')).decode("ascii")
headers = { 'Authorization' : 'Basic %s' %  userAndPass }

def check_and_run():
    pathlib.Path('_data').mkdir(parents=True, exist_ok=True)
    try:
        with open(r'./_data/recipes_status.json', 'rb') as file:
            old_data = file.read()
    except IOError as error:
        open(r'./_data/recipes_status.json', 'wb+').close() 
        old_data = "{}"
    c.request('GET', '/api/v1/sync/status/', headers=headers)
    res = c.getresponse()
    new_data = res.read()
    if new_data != old_data:
        with open(r'./_data/recipes_status.json', 'wb+') as file:
            file.write(new_data)
        export_recipes()

def export_recipes():

    pathlib.Path(r'_data').mkdir(parents=True, exist_ok=True)
    pathlib.Path('assets/images/recipes').mkdir(parents=True, exist_ok=True)
    c.request('GET', '/api/v1/sync/categories/', headers=headers)
    res = c.getresponse()
    data = res.read()
    categories = {}
    try:
        category_items = json.loads(data)['result']
    except (KeyError, ValueError):
        print('no category list in payload; continuing without categories')
        category_items = []
    for item in category_items:
        categories[item['uid']] = item['name']


    c.request('GET', '/api/v1/sync/recipes/', headers=headers)
    res = c.getresponse()
    data = res.read()

    recipes = []

    try:
        recipe_items = json.loads(data)['result']
    except (KeyError, ValueError):
        print('no recipe list in payload; aborting export (keeping last recipes.yaml)')
        return

    for item in recipe_items:
        c.request('GET', '/api/v1/sync/recipe/'+item['uid']+'/', headers=headers)
        res = c.getresponse()
        data = res.read()
        try:
            recipe = json.loads(data)['result']
        except (KeyError, ValueError):
            print('  no data for recipe', item['uid'], '- skipping')
            continue
        # https://gist.github.com/mattdsteele/7386ec363badfdeaad05a418b9a1f30a
        print(recipe['name'])
        if recipe.get('photo_large'):
            recipe['photo'] = recipe['photo_large']
            addr = recipe['photo_large'][:-4]
            c.request('GET', "/api/v1/sync/photo/"+addr+"/", headers=headers)
            res = c.getresponse()
            data = res.read()
            try:
                photoData = json.loads(data)['result']
                recipe['photo_url'] = photoData['photo_url']
            except (KeyError, ValueError):
                print('  no photo data for', recipe['name'], '- skipping')


        if recipe.get('photo') and recipe.get('photo_url') and recipe['photo_url'].startswith('http://uploads.paprikaapp.com.s3.amazonaws.com'):
            resp = requests.get(recipe['photo_url'], stream=True)
            local_file = open('assets/images/recipes/'+recipe['photo'], 'wb')
            resp.raw.decode_content = True
            shutil.copyfileobj(resp.raw, local_file)
            recipe['image_url'] = 'images/recipes/'+recipe['photo']


        for photo_key in ('photo_url', 'photo', 'hash', 'photo_hash', 'photo_large'):
            recipe.pop(photo_key, None)

        recipe['photos'] = []

        if recipe['directions']:
            directions = recipe['directions'].split('\n')
            recipe['directions'] = []
            for direction in directions:
                if direction != '':
                    recipe['directions'].append(direction)

        if recipe['ingredients']:
            ingredients = recipe['ingredients'].split('\n')
            recipe['ingredients'] = []
            for ingredient in ingredients:
                if ingredient != '':
                    recipe['ingredients'].append(ingredient)

        if recipe['categories']:
            categoryList = []
            for category in recipe['categories']:
                categoryList.append(categories.get(category, category))
            recipe['categories'] = categoryList

        recipes.append(recipe)

    # this gets all photos
    c.request('GET', '/api/v1/sync/photos/', headers=headers)
    res = c.getresponse()
    data = res.read()
    try:
        photos = json.loads(data)['result']
    except (KeyError, ValueError):
        print('no photo list in payload; skipping photo export')
        photos = []
    print("\n\n")
    print("Photos")
    for item in photos:
        c.request('GET', '/api/v1/sync/photo/'+item['uid']+'/', headers=headers)
        res = c.getresponse()
        data = res.read()
        try:
            photo = json.loads(data)['result']
        except (KeyError, ValueError):
            print('  no data for photo item', item.get('uid'), '- skipping')
            continue
        rec = [x for x in recipes if x['uid'] == photo.get('recipe_uid')]
        if not rec:
            print('skipping photo with no matching recipe:', photo.get('name', photo.get('uid', '?')))
            continue
        if not photo.get('photo_url'):
            print('skipping photo without photo_url:', photo.get('name', photo.get('uid', '?')))
            continue
        print(rec[0]['name'])
        # create newphoto dict with uid and filename
        newphoto = {}
        photo_name = photo['name']
        newphoto[photo_name] = 'images/recipes/'+photo['filename']
        rec[0]['photos'].append(newphoto)
        resp = requests.get(photo['photo_url'], stream=True)
        local_file = open('assets/images/recipes/'+photo['filename'], 'wb')
        resp.raw.decode_content = True
        shutil.copyfileobj(resp.raw, local_file)

    with open(r'./_data/recipes.yaml', 'w') as file:
        yaml.safe_dump(recipes, file)

if __name__ == "__main__":
    check_and_run()
