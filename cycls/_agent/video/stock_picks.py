"""Stock clips of Gulf subjects, picked by eye from Pexels: a search about one of these subjects is offered them
before what the search finds (stock.find). A search for "arabic coffee" mostly finds Turkish coffee in handled cups
and one for "kabsa" biryani, so the clips a Saudi brand would use are kept here, with what each topic's searches say.

Written by cycls-video/scripts/lab/gulf_module.py from the screened clips less the ones the person dropped on the
tick page; each clip as a search result is (its page, size, length, filmmaker, the MP4 to fetch), so offering it
costs no call to Pexels. A clip Pexels has since removed fails to fetch and the model picks the next one.
"""
import re

PATTERNS = {
    'coffee': re.compile('\\b(dallah|finjaa?ns?|qahwa|gahwa|kahwa)\\b|\\b(arabic|arabian|saudi|gulf|khaleeji|bedouin|emirati)\\b[\\w\\s]{0,20}\\bcoffee\\b|قهوة|دل[ّ]?ة|فناجي?ن', re.I),
    'dates': re.compile('\\b(dates|medjool|ajwa|sukkari|date palms?|date fruits?|date farm)\\b|تمور|تمر|نخيل|نخل', re.I),
    'feast': re.compile('\\b(kabsa|kapsa|mandi|machboos|majboos|mansaf|madfoon|mathbi|haneeth)\\b|\\b(arabic|arabian|saudi|gulf|bedouin)\\b[\\w\\s]{0,20}\\b(rice|feast|food|platter|lamb)\\b|كبسة|مندي|مفطح|مضغوط|ذبيحة', re.I),
    'majlis': re.compile('\\bmajlis\\b|\\b(arab|arabic|saudi|gulf|emirati|bedouin)\\b[\\w\\s]{0,20}\\b(hospitality|gathering|tea|serving)\\b|مجلس|ضيافة', re.I),
    'business': re.compile('\\b(arab|arabic|saudi|gulf|emirati|khaleeji)\\b[\\w\\s]{0,20}\\b(business|businessm[ae]n|meeting|office|entrepreneurs?|laptop|executives?|handshake)\\b|رجل أعمال|رجال أعمال|اجتماع', re.I),
    'people': re.compile('\\b(thobes?|thawbs?|ghutra|shemagh|keffiyeh|kandura|abayas?|niqab)\\b|\\b(saudi|emirati|khaleeji|gulf|arab)\\b[\\w\\s]{0,20}\\b(man|men|woman|women|people|boy|girl|family|person|businessm[ae]n)\\b|سعودي|خليجي', re.I),
    'riyadh': re.compile('\\briy[a]?dh?\\b|\\bkingdom (cent(re|er)|tower)\\b|\\bsaudi\\b[\\w\\s]{0,20}\\b(city|skyline|street|road|traffic|tower)\\b|الرياض', re.I),
    'jeddah': re.compile('\\bjedd?ah?\\b|\\bcorniche\\b|\\bred sea\\b|\\bal[- ]?balad\\b|جدة|الكورنيش|البحر الأحمر', re.I),
    'desert': re.compile('\\b(desert|dunes?|camels?|bedouin|sand dunes?|empty quarter|rub al khali)\\b|صحراء|صحراوي|كثبان|رمال|جمل|إبل|هجن', re.I),
    'ramadan': re.compile('\\b(ramadan|ramazan|iftar|suhoor|sahur|eid|fanoos|fanous)\\b|\\bramadan lanterns?\\b|\\bcrescent\\b[\\w\\s]{0,15}\\b(moon|lantern|decoration)\\b|رمضان|إفطار|افطار|سحور|عيد|فانوس|هلال', re.I),
    'incense': re.compile('\\b(bakhoor|bukhoor|bakhour|mabkhara|incense burner|oud (incense|wood|chips|smoke))\\b|\\barab(ic|ian)? incense\\b|بخور|مبخرة', re.I),
    'heritage': re.compile('\\b(al[- ]?ula|hegra|mada.?in sal(e|i)h|diriyah|najdi|mud[- ]?brick|adobe|wind tower|barjeel|souq|souk|elephant rock)\\b|\\b(saudi|arabian|gulf|arab)\\b[\\w\\s]{0,20}\\b(heritage|old town|fort|village)\\b|العلا|الدرعية|تراث|قصر|سوق شعبي', re.I),
    'mosque': re.compile('\\b(mosques?|minarets?|masjid)\\b|مسجد|جامع|مئذنة', re.I),
}

CLIPS = {
 "coffee": [
  {
   "id": 6358277,
   "url": "https://www.pexels.com/video/person-pouring-coffee-into-dallah-6358277/",
   "duration": 13,
   "width": 1920,
   "height": 1080,
   "user": {
    "name": "Ibrahim Bennett"
   },
   "video_files": [
    {
     "file_type": "video/mp4",
     "width": 1920,
     "height": 1080,
     "link": "https://videos.pexels.com/video-files/6358277/6358277-hd_1920_1080_30fps.mp4"
    }
   ]
  },
  {
   "id": 5988416,
   "url": "https://www.pexels.com/video/a-man-pouring-tea-on-a-tea-cup-5988416/",
   "duration": 17,
   "width": 3840,
   "height": 2160,
   "user": {
    "name": "Tima Miroshnichenko"
   },
   "video_files": [
    {
     "file_type": "video/mp4",
     "width": 1920,
     "height": 1080,
     "link": "https://videos.pexels.com/video-files/5988416/5988416-hd_1920_1080_25fps.mp4"
    }
   ]
  },
  {
   "id": 5988413,
   "url": "https://www.pexels.com/video/a-person-putting-charcoal-on-a-bowl-5988413/",
   "duration": 15,
   "width": 3840,
   "height": 2160,
   "user": {
    "name": "Tima Miroshnichenko"
   },
   "video_files": [
    {
     "file_type": "video/mp4",
     "width": 1920,
     "height": 1080,
     "link": "https://videos.pexels.com/video-files/5988413/5988413-hd_1920_1080_25fps.mp4"
    }
   ]
  },
  {
   "id": 5988662,
   "url": "https://www.pexels.com/video/man-pouring-and-drinking-his-tea-5988662/",
   "duration": 21,
   "width": 2160,
   "height": 3840,
   "user": {
    "name": "Tima Miroshnichenko"
   },
   "video_files": [
    {
     "file_type": "video/mp4",
     "width": 1080,
     "height": 1920,
     "link": "https://videos.pexels.com/video-files/5988662/5988662-hd_1080_1920_25fps.mp4"
    }
   ]
  }
 ],
 "dates": [
  {
   "id": 20497427,
   "url": "https://www.pexels.com/video/a-bowl-of-dates-with-a-plate-of-dates-on-top-20497427/",
   "duration": 4,
   "width": 1080,
   "height": 1920,
   "user": {
    "name": "Ammad Rasool"
   },
   "video_files": [
    {
     "file_type": "video/mp4",
     "width": 1080,
     "height": 1920,
     "link": "https://videos.pexels.com/video-files/20497427/20497427-hd_1080_1920_25fps.mp4"
    }
   ]
  },
  {
   "id": 855683,
   "url": "https://www.pexels.com/video/low-angle-shot-of-date-palm-tree-855683/",
   "duration": 11,
   "width": 1920,
   "height": 1080,
   "user": {
    "name": "Pixabay"
   },
   "video_files": [
    {
     "file_type": "video/mp4",
     "width": 1920,
     "height": 1080,
     "link": "https://videos.pexels.com/video-files/855683/855683-hd_1920_1080_24fps.mp4"
    }
   ]
  },
  {
   "id": 36326071,
   "url": "https://www.pexels.com/video/assorted-dried-fruits-in-market-stall-display-36326071/",
   "duration": 11,
   "width": 3840,
   "height": 2160,
   "user": {
    "name": "Sururi Ballıdağ Director"
   },
   "video_files": [
    {
     "file_type": "video/mp4",
     "width": 1920,
     "height": 1080,
     "link": "https://videos.pexels.com/video-files/36326071/15405970_1920_1080_50fps.mp4"
    }
   ]
  },
  {
   "id": 40927811,
   "url": "https://www.pexels.com/video/colorful-spice-bazaar-with-assorted-dried-fruits-40927811/",
   "duration": 7,
   "width": 2688,
   "height": 1512,
   "user": {
    "name": "Sururi Ballıdağ Director"
   },
   "video_files": [
    {
     "file_type": "video/mp4",
     "width": 1920,
     "height": 1080,
     "link": "https://videos.pexels.com/video-files/40927811/17498958_1920_1080_25fps.mp4"
    }
   ]
  },
  {
   "id": 14160251,
   "url": "https://www.pexels.com/video/low-angle-view-of-a-date-palm-tree-14160251/",
   "duration": 18,
   "width": 4096,
   "height": 2160,
   "user": {
    "name": "Engin Akyurt"
   },
   "video_files": [
    {
     "file_type": "video/mp4",
     "width": 1366,
     "height": 720,
     "link": "https://videos.pexels.com/video-files/14160251/14160251-hd_1366_720_30fps.mp4"
    }
   ]
  },
  {
   "id": 18843147,
   "url": "https://www.pexels.com/video/traditional-market-souk-saudi-arabia-18843147/",
   "duration": 6,
   "width": 2560,
   "height": 1440,
   "user": {
    "name": "Aamir Somewhere"
   },
   "video_files": [
    {
     "file_type": "video/mp4",
     "width": 1920,
     "height": 1080,
     "link": "https://videos.pexels.com/video-files/18843147/18843147-hd_1920_1080_30fps.mp4"
    }
   ]
  },
  {
   "id": 28949922,
   "url": "https://www.pexels.com/video/vast-palm-plantation-at-sunrise-28949922/",
   "duration": 17,
   "width": 2560,
   "height": 1440,
   "user": {
    "name": "Sahara  Farms"
   },
   "video_files": [
    {
     "file_type": "video/mp4",
     "width": 1920,
     "height": 1080,
     "link": "https://videos.pexels.com/video-files/28949922/12525958_1920_1080_30fps.mp4"
    }
   ]
  },
  {
   "id": 18940113,
   "url": "https://www.pexels.com/video/a-person-s-hand-is-holding-a-bowl-of-food-18940113/",
   "duration": 15,
   "width": 1080,
   "height": 1920,
   "user": {
    "name": "Kuiyibo Campos"
   },
   "video_files": [
    {
     "file_type": "video/mp4",
     "width": 1080,
     "height": 1920,
     "link": "https://videos.pexels.com/video-files/18940113/18940113-hd_1080_1920_30fps.mp4"
    }
   ]
  },
  {
   "id": 20497423,
   "url": "https://www.pexels.com/video/a-bowl-of-dates-on-a-dark-background-20497423/",
   "duration": 10,
   "width": 3840,
   "height": 2160,
   "user": {
    "name": "Ammad Rasool"
   },
   "video_files": [
    {
     "file_type": "video/mp4",
     "width": 1920,
     "height": 1080,
     "link": "https://videos.pexels.com/video-files/20497423/20497423-hd_1920_1080_25fps.mp4"
    }
   ]
  },
  {
   "id": 20497501,
   "url": "https://www.pexels.com/video/dates-in-a-box-on-a-black-background-20497501/",
   "duration": 21,
   "width": 1920,
   "height": 1080,
   "user": {
    "name": "Ammad Rasool"
   },
   "video_files": [
    {
     "file_type": "video/mp4",
     "width": 1920,
     "height": 1080,
     "link": "https://videos.pexels.com/video-files/20497501/20497501-hd_1920_1080_25fps.mp4"
    }
   ]
  },
  {
   "id": 8166038,
   "url": "https://www.pexels.com/video/a-woman-holding-a-tray-with-dates-and-glass-of-water-8166038/",
   "duration": 7,
   "width": 2160,
   "height": 3840,
   "user": {
    "name": "Alena Darmel"
   },
   "video_files": [
    {
     "file_type": "video/mp4",
     "width": 1080,
     "height": 1920,
     "link": "https://videos.pexels.com/video-files/8166038/8166038-hd_1080_1920_25fps.mp4"
    }
   ]
  },
  {
   "id": 28961815,
   "url": "https://www.pexels.com/video/tropical-palm-trees-on-a-sunny-day-28961815/",
   "duration": 50,
   "width": 2160,
   "height": 3840,
   "user": {
    "name": "Engin Akyurt"
   },
   "video_files": [
    {
     "file_type": "video/mp4",
     "width": 1080,
     "height": 1920,
     "link": "https://videos.pexels.com/video-files/28961815/12529481_1080_1920_30fps.mp4"
    }
   ]
  }
 ],
 "feast": [
  {
   "id": 34453035,
   "url": "https://www.pexels.com/video/delicious-arabian-inspired-chicken-dish-34453035/",
   "duration": 11,
   "width": 2160,
   "height": 3840,
   "user": {
    "name": "Evgenij Mikhailov"
   },
   "video_files": [
    {
     "file_type": "video/mp4",
     "width": 1080,
     "height": 1920,
     "link": "https://videos.pexels.com/video-files/34453035/14599343_1080_1920_60fps.mp4"
    }
   ]
  },
  {
   "id": 34776140,
   "url": "https://www.pexels.com/video/authentic-outdoor-cooking-of-traditional-dish-34776140/",
   "duration": 6,
   "width": 2160,
   "height": 3840,
   "user": {
    "name": "Umar Saudagar"
   },
   "video_files": [
    {
     "file_type": "video/mp4",
     "width": 1080,
     "height": 1920,
     "link": "https://videos.pexels.com/video-files/34776140/14743291_1080_1920_30fps.mp4"
    }
   ]
  },
  {
   "id": 10200319,
   "url": "https://www.pexels.com/video/close-up-of-hot-rice-meal-10200319/",
   "duration": 11,
   "width": 2160,
   "height": 3840,
   "user": {
    "name": "宇航 钱"
   },
   "video_files": [
    {
     "file_type": "video/mp4",
     "width": 1080,
     "height": 1920,
     "link": "https://videos.pexels.com/video-files/10200319/10200319-hd_1080_1920_25fps.mp4"
    }
   ]
  },
  {
   "id": 5134443,
   "url": "https://www.pexels.com/video/cooking-grilled-chicken-on-charcoal-5134443/",
   "duration": 16,
   "width": 1920,
   "height": 1080,
   "user": {
    "name": "MK Collection"
   },
   "video_files": [
    {
     "file_type": "video/mp4",
     "width": 1920,
     "height": 1080,
     "link": "https://videos.pexels.com/video-files/5134443/5134443-hd_1920_1080_30fps.mp4"
    }
   ]
  },
  {
   "id": 34453033,
   "url": "https://www.pexels.com/video/delicious-lamb-dish-with-rice-preparation-34453033/",
   "duration": 28,
   "width": 2160,
   "height": 3840,
   "user": {
    "name": "Evgenij Mikhailov"
   },
   "video_files": [
    {
     "file_type": "video/mp4",
     "width": 1080,
     "height": 1920,
     "link": "https://videos.pexels.com/video-files/34453033/14599361_1080_1920_60fps.mp4"
    }
   ]
  },
  {
   "id": 34129125,
   "url": "https://www.pexels.com/video/elegant-dinner-adventure-fish-and-rice-feast-34129125/",
   "duration": 14,
   "width": 2160,
   "height": 3840,
   "user": {
    "name": "Evgenij Mikhailov"
   },
   "video_files": [
    {
     "file_type": "video/mp4",
     "width": 1080,
     "height": 1920,
     "link": "https://videos.pexels.com/video-files/34129125/14472131_1080_1920_60fps.mp4"
    }
   ]
  },
  {
   "id": 34803490,
   "url": "https://www.pexels.com/video/traditional-wood-fired-outdoor-cooking-with-pot-34803490/",
   "duration": 15,
   "width": 1080,
   "height": 2336,
   "user": {
    "name": "Ahila devi Manoharan"
   },
   "video_files": [
    {
     "file_type": "video/mp4",
     "width": 720,
     "height": 1558,
     "link": "https://videos.pexels.com/video-files/34803490/14756627_720_1558_30fps.mp4"
    }
   ]
  },
  {
   "id": 25822981,
   "url": "https://www.pexels.com/video/shawarma-25822981/",
   "duration": 12,
   "width": 2160,
   "height": 3840,
   "user": {
    "name": "khezez  | خزاز"
   },
   "video_files": [
    {
     "file_type": "video/mp4",
     "width": 1080,
     "height": 1920,
     "link": "https://videos.pexels.com/video-files/25822981/11912127_1080_1920_60fps.mp4"
    }
   ]
  },
  {
   "id": 37047000,
   "url": "https://www.pexels.com/video/slicing-delicious-shawarma-meat-close-up-37047000/",
   "duration": 12,
   "width": 1440,
   "height": 2560,
   "user": {
    "name": "OHXZONE"
   },
   "video_files": [
    {
     "file_type": "video/mp4",
     "width": 1080,
     "height": 1920,
     "link": "https://videos.pexels.com/video-files/37047000/15694052_1080_1920_60fps.mp4"
    }
   ]
  }
 ],
 "business": [
  {
   "id": 7975473,
   "url": "https://www.pexels.com/video/man-using-a-laptop-7975473/",
   "duration": 21,
   "width": 1080,
   "height": 1920,
   "user": {
    "name": "Thirdman"
   },
   "video_files": [
    {
     "file_type": "video/mp4",
     "width": 1080,
     "height": 1920,
     "link": "https://videos.pexels.com/video-files/7975473/7975473-hd_1080_1920_25fps.mp4"
    }
   ]
  },
  {
   "id": 8939826,
   "url": "https://www.pexels.com/video/man-wearing-head-scarf-typing-on-laptop-8939826/",
   "duration": 13,
   "width": 1080,
   "height": 1920,
   "user": {
    "name": "Mikhail Nilov"
   },
   "video_files": [
    {
     "file_type": "video/mp4",
     "width": 1080,
     "height": 1920,
     "link": "https://videos.pexels.com/video-files/8939826/8939826-hd_1080_1920_25fps.mp4"
    }
   ]
  },
  {
   "id": 8940135,
   "url": "https://www.pexels.com/video/a-man-putting-on-his-eyeglasses-8940135/",
   "duration": 18,
   "width": 1080,
   "height": 1920,
   "user": {
    "name": "Mikhail Nilov"
   },
   "video_files": [
    {
     "file_type": "video/mp4",
     "width": 1080,
     "height": 1920,
     "link": "https://videos.pexels.com/video-files/8940135/8940135-hd_1080_1920_25fps.mp4"
    }
   ]
  },
  {
   "id": 7975463,
   "url": "https://www.pexels.com/video/men-shaking-hands-7975463/",
   "duration": 21,
   "width": 1920,
   "height": 1080,
   "user": {
    "name": "Thirdman"
   },
   "video_files": [
    {
     "file_type": "video/mp4",
     "width": 1920,
     "height": 1080,
     "link": "https://videos.pexels.com/video-files/7975463/7975463-hd_1920_1080_25fps.mp4"
    }
   ]
  },
  {
   "id": 8939822,
   "url": "https://www.pexels.com/video/men-talking-while-swinging-on-their-chairs-8939822/",
   "duration": 13,
   "width": 1920,
   "height": 1080,
   "user": {
    "name": "Mikhail Nilov"
   },
   "video_files": [
    {
     "file_type": "video/mp4",
     "width": 1920,
     "height": 1080,
     "link": "https://videos.pexels.com/video-files/8939822/8939822-hd_1920_1080_25fps.mp4"
    }
   ]
  },
  {
   "id": 7975479,
   "url": "https://www.pexels.com/video/men-in-a-business-meeting-7975479/",
   "duration": 18,
   "width": 1920,
   "height": 1080,
   "user": {
    "name": "Thirdman"
   },
   "video_files": [
    {
     "file_type": "video/mp4",
     "width": 1920,
     "height": 1080,
     "link": "https://videos.pexels.com/video-files/7975479/7975479-hd_1920_1080_25fps.mp4"
    }
   ]
  },
  {
   "id": 8940136,
   "url": "https://www.pexels.com/video/a-man-sitting-while-holding-an-eyeglasses-8940136/",
   "duration": 14,
   "width": 1920,
   "height": 1080,
   "user": {
    "name": "Mikhail Nilov"
   },
   "video_files": [
    {
     "file_type": "video/mp4",
     "width": 1920,
     "height": 1080,
     "link": "https://videos.pexels.com/video-files/8940136/8940136-hd_1920_1080_25fps.mp4"
    }
   ]
  }
 ],
 "majlis": [
  {
   "id": 39451873,
   "url": "https://www.pexels.com/video/elegant-arabic-tea-ceremony-in-warm-setting-39451873/",
   "duration": 12,
   "width": 2496,
   "height": 3328,
   "user": {
    "name": "Aabouden Yassir"
   },
   "video_files": [
    {
     "file_type": "video/mp4",
     "width": 1440,
     "height": 1920,
     "link": "https://videos.pexels.com/video-files/39451873/16801682_1440_1920_25fps.mp4"
    }
   ]
  }
 ],
 "people": [
  {
   "id": 38407319,
   "url": "https://www.pexels.com/video/man-feeding-pigeons-in-outdoor-public-square-38407319/",
   "duration": 5,
   "width": 1080,
   "height": 1920,
   "user": {
    "name": "ANJUM SHAHZAD"
   },
   "video_files": [
    {
     "file_type": "video/mp4",
     "width": 1080,
     "height": 1920,
     "link": "https://videos.pexels.com/video-files/38407319/16308931_1080_1920_30fps.mp4"
    }
   ]
  },
  {
   "id": 8939821,
   "url": "https://www.pexels.com/video/a-man-wearing-hijab-while-looking-at-laptop-8939821/",
   "duration": 17,
   "width": 1920,
   "height": 1080,
   "user": {
    "name": "Mikhail Nilov"
   },
   "video_files": [
    {
     "file_type": "video/mp4",
     "width": 1920,
     "height": 1080,
     "link": "https://videos.pexels.com/video-files/8939821/8939821-hd_1920_1080_25fps.mp4"
    }
   ]
  },
  {
   "id": 19437871,
   "url": "https://www.pexels.com/video/sky-man-skyscrapers-sony-19437871/",
   "duration": 8,
   "width": 3840,
   "height": 2160,
   "user": {
    "name": "Volkan Yılmaz"
   },
   "video_files": [
    {
     "file_type": "video/mp4",
     "width": 1920,
     "height": 1080,
     "link": "https://videos.pexels.com/video-files/19437871/19437871-hd_1920_1080_25fps.mp4"
    }
   ]
  },
  {
   "id": 7126085,
   "url": "https://www.pexels.com/video/man-wearing-white-thobe-7126085/",
   "duration": 10,
   "width": 2160,
   "height": 3840,
   "user": {
    "name": "Michael Burrows"
   },
   "video_files": [
    {
     "file_type": "video/mp4",
     "width": 1080,
     "height": 1920,
     "link": "https://videos.pexels.com/video-files/7126085/7126085-hd_1080_1920_24fps.mp4"
    }
   ]
  },
  {
   "id": 5988794,
   "url": "https://www.pexels.com/video/man-in-white-thawb-walking-outdoors-5988794/",
   "duration": 7,
   "width": 3840,
   "height": 2160,
   "user": {
    "name": "Tima Miroshnichenko"
   },
   "video_files": [
    {
     "file_type": "video/mp4",
     "width": 1920,
     "height": 1080,
     "link": "https://videos.pexels.com/video-files/5988794/5988794-hd_1920_1080_25fps.mp4"
    }
   ]
  }
 ],
 "riyadh": [
  {
   "id": 35626508,
   "url": "https://www.pexels.com/video/saudi-arabia-tower-and-flag-with-palm-trees-35626508/",
   "duration": 6,
   "width": 1080,
   "height": 1920,
   "user": {
    "name": "Asad  Ansari"
   },
   "video_files": [
    {
     "file_type": "video/mp4",
     "width": 1080,
     "height": 1920,
     "link": "https://videos.pexels.com/video-files/35626508/15097823_1080_1920_60fps.mp4"
    }
   ]
  },
  {
   "id": 34505477,
   "url": "https://www.pexels.com/video/kingdom-tower-with-light-show-in-riyadh-34505477/",
   "duration": 20,
   "width": 2160,
   "height": 3840,
   "user": {
    "name": "Grbr Snts"
   },
   "video_files": [
    {
     "file_type": "video/mp4",
     "width": 1080,
     "height": 1920,
     "link": "https://videos.pexels.com/video-files/34505477/14619964_1080_1920_30fps.mp4"
    }
   ]
  },
  {
   "id": 34505476,
   "url": "https://www.pexels.com/video/kingdom-tower-illuminated-at-night-in-riyadh-34505476/",
   "duration": 14,
   "width": 2160,
   "height": 3840,
   "user": {
    "name": "Grbr Snts"
   },
   "video_files": [
    {
     "file_type": "video/mp4",
     "width": 1080,
     "height": 1920,
     "link": "https://videos.pexels.com/video-files/34505476/14619958_1080_1920_30fps.mp4"
    }
   ]
  },
  {
   "id": 35255336,
   "url": "https://www.pexels.com/video/stunning-urban-sunset-with-red-sky-and-plane-35255336/",
   "duration": 17,
   "width": 1080,
   "height": 1920,
   "user": {
    "name": "Shanu Azhikode"
   },
   "video_files": [
    {
     "file_type": "video/mp4",
     "width": 1080,
     "height": 1920,
     "link": "https://videos.pexels.com/video-files/35255336/14935858_1080_1920_60fps.mp4"
    }
   ]
  },
  {
   "id": 18511357,
   "url": "https://www.pexels.com/video/riyadh-skyline-18511357/",
   "duration": 18,
   "width": 2268,
   "height": 4032,
   "user": {
    "name": "Abdul7amid Al Fadhly"
   },
   "video_files": [
    {
     "file_type": "video/mp4",
     "width": 1080,
     "height": 1920,
     "link": "https://videos.pexels.com/video-files/18511357/18511357-hd_1080_1920_30fps.mp4"
    }
   ]
  },
  {
   "id": 9109489,
   "url": "https://www.pexels.com/video/a-view-of-the-city-at-daylight-9109489/",
   "duration": 14,
   "width": 2720,
   "height": 1530,
   "user": {
    "name": "Shoot With Riyas"
   },
   "video_files": [
    {
     "file_type": "video/mp4",
     "width": 1920,
     "height": 1080,
     "link": "https://videos.pexels.com/video-files/9109489/9109489-hd_1920_1080_30fps.mp4"
    }
   ]
  },
  {
   "id": 41007989,
   "url": "https://www.pexels.com/video/urban-intersection-with-traffic-in-riyadh-41007989/",
   "duration": 8,
   "width": 3840,
   "height": 2160,
   "user": {
    "name": "Muhammad Sajjad Ahmad"
   },
   "video_files": [
    {
     "file_type": "video/mp4",
     "width": 1920,
     "height": 1080,
     "link": "https://videos.pexels.com/video-files/41007989/17545598_1920_1080_30fps.mp4"
    }
   ]
  },
  {
   "id": 13217151,
   "url": "https://www.pexels.com/video/highway-traffic-in-the-city-of-riyadh-saudi-arabia-13217151/",
   "duration": 16,
   "width": 3840,
   "height": 2160,
   "user": {
    "name": "M1DDL3  M7N"
   },
   "video_files": [
    {
     "file_type": "video/mp4",
     "width": 1920,
     "height": 1080,
     "link": "https://videos.pexels.com/video-files/13217151/13217151-hd_1920_1080_60fps.mp4"
    }
   ]
  },
  {
   "id": 9102494,
   "url": "https://www.pexels.com/video/driving-in-the-streets-of-riyadh-9102494/",
   "duration": 17,
   "width": 1920,
   "height": 1080,
   "user": {
    "name": "Shoot With Riyas"
   },
   "video_files": [
    {
     "file_type": "video/mp4",
     "width": 1920,
     "height": 1080,
     "link": "https://videos.pexels.com/video-files/9102494/9102494-hd_1920_1080_30fps.mp4"
    }
   ]
  },
  {
   "id": 8106979,
   "url": "https://www.pexels.com/video/push-in-shot-of-king-khaled-international-airport-grand-mosque-8106979/",
   "duration": 15,
   "width": 3840,
   "height": 2160,
   "user": {
    "name": "Shoot With Riyas"
   },
   "video_files": [
    {
     "file_type": "video/mp4",
     "width": 1920,
     "height": 1080,
     "link": "https://videos.pexels.com/video-files/8106979/8106979-hd_1920_1080_30fps.mp4"
    }
   ]
  },
  {
   "id": 19102792,
   "url": "https://www.pexels.com/video/arab-19102792/",
   "duration": 21,
   "width": 4096,
   "height": 2160,
   "user": {
    "name": "ibrahim almuhanna"
   },
   "video_files": [
    {
     "file_type": "video/mp4",
     "width": 1366,
     "height": 720,
     "link": "https://videos.pexels.com/video-files/19102792/19102792-hd_1366_720_24fps.mp4"
    }
   ]
  }
 ],
 "jeddah": [
  {
   "id": 31535581,
   "url": "https://www.pexels.com/video/scenic-view-of-jeddah-corniche-mosque-31535581/",
   "duration": 18,
   "width": 2160,
   "height": 3840,
   "user": {
    "name": "Md Amir Umar"
   },
   "video_files": [
    {
     "file_type": "video/mp4",
     "width": 1080,
     "height": 1920,
     "link": "https://videos.pexels.com/video-files/31535581/13440957_1080_1920_30fps.mp4"
    }
   ]
  },
  {
   "id": 34747167,
   "url": "https://www.pexels.com/video/stunning-view-of-jeddah-s-modern-corniche-34747167/",
   "duration": 15,
   "width": 2160,
   "height": 3840,
   "user": {
    "name": "Md Amir Umar"
   },
   "video_files": [
    {
     "file_type": "video/mp4",
     "width": 1080,
     "height": 1920,
     "link": "https://videos.pexels.com/video-files/34747167/14730182_1080_1920_30fps.mp4"
    }
   ]
  },
  {
   "id": 31535594,
   "url": "https://www.pexels.com/video/scenic-view-of-jeddah-corniche-and-skyline-31535594/",
   "duration": 9,
   "width": 2160,
   "height": 3840,
   "user": {
    "name": "Md Amir Umar"
   },
   "video_files": [
    {
     "file_type": "video/mp4",
     "width": 1080,
     "height": 1920,
     "link": "https://videos.pexels.com/video-files/31535594/13440939_1080_1920_30fps.mp4"
    }
   ]
  },
  {
   "id": 34653347,
   "url": "https://www.pexels.com/video/serene-waterfront-promenade-with-tall-palms-34653347/",
   "duration": 20,
   "width": 1080,
   "height": 1920,
   "user": {
    "name": "Faisal Abdullah"
   },
   "video_files": [
    {
     "file_type": "video/mp4",
     "width": 1080,
     "height": 1920,
     "link": "https://videos.pexels.com/video-files/34653347/14688165_1080_1920_30fps.mp4"
    }
   ]
  },
  {
   "id": 34747290,
   "url": "https://www.pexels.com/video/jeddah-corniche-with-iconic-waterfront-architecture-34747290/",
   "duration": 17,
   "width": 3840,
   "height": 2160,
   "user": {
    "name": "Md Amir Umar"
   },
   "video_files": [
    {
     "file_type": "video/mp4",
     "width": 1920,
     "height": 1080,
     "link": "https://videos.pexels.com/video-files/34747290/14730266_1920_1080_30fps.mp4"
    }
   ]
  },
  {
   "id": 34747276,
   "url": "https://www.pexels.com/video/jeddah-corniche-skyline-with-iconic-tower-34747276/",
   "duration": 18,
   "width": 3840,
   "height": 2160,
   "user": {
    "name": "Md Amir Umar"
   },
   "video_files": [
    {
     "file_type": "video/mp4",
     "width": 1920,
     "height": 1080,
     "link": "https://videos.pexels.com/video-files/34747276/14730279_1920_1080_30fps.mp4"
    }
   ]
  },
  {
   "id": 34747099,
   "url": "https://www.pexels.com/video/jeddah-corniche-seaside-with-modern-architecture-34747099/",
   "duration": 14,
   "width": 3840,
   "height": 2160,
   "user": {
    "name": "Md Amir Umar"
   },
   "video_files": [
    {
     "file_type": "video/mp4",
     "width": 1920,
     "height": 1080,
     "link": "https://videos.pexels.com/video-files/34747099/14730176_1920_1080_30fps.mp4"
    }
   ]
  },
  {
   "id": 34747297,
   "url": "https://www.pexels.com/video/scenic-walk-on-jeddah-corniche-waterfront-34747297/",
   "duration": 15,
   "width": 2160,
   "height": 3840,
   "user": {
    "name": "Md Amir Umar"
   },
   "video_files": [
    {
     "file_type": "video/mp4",
     "width": 1080,
     "height": 1920,
     "link": "https://videos.pexels.com/video-files/34747297/14730230_1080_1920_30fps.mp4"
    }
   ]
  },
  {
   "id": 34747333,
   "url": "https://www.pexels.com/video/scenic-view-of-jeddah-corniche-landmark-34747333/",
   "duration": 20,
   "width": 2160,
   "height": 3840,
   "user": {
    "name": "Md Amir Umar"
   },
   "video_files": [
    {
     "file_type": "video/mp4",
     "width": 1080,
     "height": 1920,
     "link": "https://videos.pexels.com/video-files/34747333/14730289_1080_1920_30fps.mp4"
    }
   ]
  },
  {
   "id": 34747299,
   "url": "https://www.pexels.com/video/scenic-walkway-along-jeddah-corniche-34747299/",
   "duration": 17,
   "width": 3840,
   "height": 2160,
   "user": {
    "name": "Md Amir Umar"
   },
   "video_files": [
    {
     "file_type": "video/mp4",
     "width": 1920,
     "height": 1080,
     "link": "https://videos.pexels.com/video-files/34747299/14730267_1920_1080_30fps.mp4"
    }
   ]
  },
  {
   "id": 36592386,
   "url": "https://www.pexels.com/video/traditional-architecture-in-historic-district-36592386/",
   "duration": 5,
   "width": 2160,
   "height": 3840,
   "user": {
    "name": "Rüveyda Akkaya"
   },
   "video_files": [
    {
     "file_type": "video/mp4",
     "width": 1080,
     "height": 1920,
     "link": "https://videos.pexels.com/video-files/36592386/15514697_1080_1920_60fps.mp4"
    }
   ]
  },
  {
   "id": 34747361,
   "url": "https://www.pexels.com/video/scenic-view-of-jeddah-s-modern-corniche-34747361/",
   "duration": 18,
   "width": 3840,
   "height": 2160,
   "user": {
    "name": "Md Amir Umar"
   },
   "video_files": [
    {
     "file_type": "video/mp4",
     "width": 1920,
     "height": 1080,
     "link": "https://videos.pexels.com/video-files/34747361/14730295_1920_1080_30fps.mp4"
    }
   ]
  }
 ],
 "desert": [
  {
   "id": 12902301,
   "url": "https://www.pexels.com/video/walking-on-a-sand-dune-in-the-desert-12902301/",
   "duration": 10,
   "width": 1080,
   "height": 1920,
   "user": {
    "name": "Mike Derkach"
   },
   "video_files": [
    {
     "file_type": "video/mp4",
     "width": 1080,
     "height": 1920,
     "link": "https://videos.pexels.com/video-files/12902301/12902301-hd_1080_1920_30fps.mp4"
    }
   ]
  },
  {
   "id": 39145684,
   "url": "https://www.pexels.com/video/serene-desert-sunset-with-flowing-sand-39145684/",
   "duration": 6,
   "width": 2160,
   "height": 3840,
   "user": {
    "name": "Mohd Atir"
   },
   "video_files": [
    {
     "file_type": "video/mp4",
     "width": 1080,
     "height": 1920,
     "link": "https://videos.pexels.com/video-files/39145684/16657949_1080_1920_60fps.mp4"
    }
   ]
  },
  {
   "id": 12902302,
   "url": "https://www.pexels.com/video/sand-ripples-in-a-desert-landscape-12902302/",
   "duration": 6,
   "width": 1080,
   "height": 1920,
   "user": {
    "name": "Mike Derkach"
   },
   "video_files": [
    {
     "file_type": "video/mp4",
     "width": 1080,
     "height": 1920,
     "link": "https://videos.pexels.com/video-files/12902302/12902302-hd_1080_1920_30fps.mp4"
    }
   ]
  },
  {
   "id": 18897114,
   "url": "https://www.pexels.com/video/dubai-s-golden-desert-18897114/",
   "duration": 10,
   "width": 2160,
   "height": 3840,
   "user": {
    "name": "Annemarie Horne"
   },
   "video_files": [
    {
     "file_type": "video/mp4",
     "width": 1080,
     "height": 1920,
     "link": "https://videos.pexels.com/video-files/18897114/18897114-hd_1080_1920_30fps.mp4"
    }
   ]
  },
  {
   "id": 32909168,
   "url": "https://www.pexels.com/video/tranquil-desert-dunes-at-sunset-32909168/",
   "duration": 8,
   "width": 2160,
   "height": 3840,
   "user": {
    "name": "Carlos Hinojosa"
   },
   "video_files": [
    {
     "file_type": "video/mp4",
     "width": 1080,
     "height": 1920,
     "link": "https://videos.pexels.com/video-files/32909168/14025681_1080_1920_30fps.mp4"
    }
   ]
  },
  {
   "id": 2055056,
   "url": "https://www.pexels.com/video/a-desert-with-view-of-sunset-2055056/",
   "duration": 12,
   "width": 1920,
   "height": 802,
   "user": {
    "name": "Phillip Chan"
   },
   "video_files": [
    {
     "file_type": "video/mp4",
     "width": 1920,
     "height": 802,
     "link": "https://videos.pexels.com/video-files/2055056/2055056-hd_1920_802_25fps.mp4"
    }
   ]
  },
  {
   "id": 5442713,
   "url": "https://www.pexels.com/video/desert-ripples-5442713/",
   "duration": 10,
   "width": 1920,
   "height": 1080,
   "user": {
    "name": "Taryn Elliott"
   },
   "video_files": [
    {
     "file_type": "video/mp4",
     "width": 1920,
     "height": 1080,
     "link": "https://videos.pexels.com/video-files/5442713/5442713-hd_1920_1080_25fps.mp4"
    }
   ]
  },
  {
   "id": 16905150,
   "url": "https://www.pexels.com/video/windy-sand-dunes-at-sunrise-16905150/",
   "duration": 21,
   "width": 3840,
   "height": 2160,
   "user": {
    "name": "Scott Unfried"
   },
   "video_files": [
    {
     "file_type": "video/mp4",
     "width": 1920,
     "height": 1080,
     "link": "https://videos.pexels.com/video-files/16905150/16905150-hd_1920_1080_24fps.mp4"
    }
   ]
  },
  {
   "id": 8865773,
   "url": "https://www.pexels.com/video/a-drone-footage-of-a-woman-walking-on-the-road-8865773/",
   "duration": 18,
   "width": 2688,
   "height": 1512,
   "user": {
    "name": "MART  PRODUCTION"
   },
   "video_files": [
    {
     "file_type": "video/mp4",
     "width": 1920,
     "height": 1080,
     "link": "https://videos.pexels.com/video-files/8865773/8865773-hd_1920_1080_25fps.mp4"
    }
   ]
  },
  {
   "id": 14862729,
   "url": "https://www.pexels.com/video/camel-ride-14862729/",
   "duration": 15,
   "width": 1080,
   "height": 1920,
   "user": {
    "name": "Rajasthan  8680"
   },
   "video_files": [
    {
     "file_type": "video/mp4",
     "width": 1080,
     "height": 1920,
     "link": "https://videos.pexels.com/video-files/14862729/14862729-hd_1080_1920_30fps.mp4"
    }
   ]
  },
  {
   "id": 30783914,
   "url": "https://www.pexels.com/video/camel-caravan-journey-through-sahara-desert-30783914/",
   "duration": 10,
   "width": 1080,
   "height": 1920,
   "user": {
    "name": "Kristen Haennel"
   },
   "video_files": [
    {
     "file_type": "video/mp4",
     "width": 1080,
     "height": 1920,
     "link": "https://videos.pexels.com/video-files/30783914/13167286_1080_1920_30fps.mp4"
    }
   ]
  },
  {
   "id": 5977848,
   "url": "https://www.pexels.com/video/herd-of-camels-in-the-desert-during-daytime-5977848/",
   "duration": 11,
   "width": 3840,
   "height": 2160,
   "user": {
    "name": "Tima Miroshnichenko"
   },
   "video_files": [
    {
     "file_type": "video/mp4",
     "width": 1920,
     "height": 1080,
     "link": "https://videos.pexels.com/video-files/5977848/5977848-hd_1920_1080_25fps.mp4"
    }
   ]
  },
  {
   "id": 7469997,
   "url": "https://www.pexels.com/video/people-riding-on-camels-in-the-desert-7469997/",
   "duration": 6,
   "width": 1920,
   "height": 1080,
   "user": {
    "name": "lifeofhicham Globetrotter Culture"
   },
   "video_files": [
    {
     "file_type": "video/mp4",
     "width": 1920,
     "height": 1080,
     "link": "https://videos.pexels.com/video-files/7469997/7469997-hd_1920_1080_25fps.mp4"
    }
   ]
  },
  {
   "id": 11215629,
   "url": "https://www.pexels.com/video/camels-drinking-on-barren-plains-11215629/",
   "duration": 9,
   "width": 1280,
   "height": 720,
   "user": {
    "name": "Dalip Khan"
   },
   "video_files": [
    {
     "file_type": "video/mp4",
     "width": 1280,
     "height": 720,
     "link": "https://videos.pexels.com/video-files/11215629/11215629-hd_1280_720_30fps.mp4"
    }
   ]
  },
  {
   "id": 855666,
   "url": "https://www.pexels.com/video/video-of-camels-855666/",
   "duration": 10,
   "width": 1920,
   "height": 1080,
   "user": {
    "name": "Pixabay"
   },
   "video_files": [
    {
     "file_type": "video/mp4",
     "width": 1920,
     "height": 1080,
     "link": "https://videos.pexels.com/video-files/855666/855666-hd_1920_1080_24fps.mp4"
    }
   ]
  }
 ],
 "ramadan": [
  {
   "id": 7952984,
   "url": "https://www.pexels.com/video/couple-eating-dinner-during-ramadan-7952984/",
   "duration": 22,
   "width": 1080,
   "height": 1920,
   "user": {
    "name": "Thirdman"
   },
   "video_files": [
    {
     "file_type": "video/mp4",
     "width": 1080,
     "height": 1920,
     "link": "https://videos.pexels.com/video-files/7952984/7952984-hd_1080_1920_25fps.mp4"
    }
   ]
  },
  {
   "id": 7953265,
   "url": "https://www.pexels.com/video/a-man-hanging-a-tassel-on-the-wall-7953265/",
   "duration": 16,
   "width": 1920,
   "height": 1080,
   "user": {
    "name": "Thirdman"
   },
   "video_files": [
    {
     "file_type": "video/mp4",
     "width": 1920,
     "height": 1080,
     "link": "https://videos.pexels.com/video-files/7953265/7953265-hd_1920_1080_25fps.mp4"
    }
   ]
  },
  {
   "id": 36587192,
   "url": "https://www.pexels.com/video/traditional-ramadan-iftar-gathering-at-dinner-table-36587192/",
   "duration": 6,
   "width": 3840,
   "height": 2160,
   "user": {
    "name": "Cemrecan Yurtman"
   },
   "video_files": [
    {
     "file_type": "video/mp4",
     "width": 1920,
     "height": 1080,
     "link": "https://videos.pexels.com/video-files/36587192/15511639_1920_1080_25fps.mp4"
    }
   ]
  },
  {
   "id": 36587398,
   "url": "https://www.pexels.com/video/communal-iftar-meal-during-ramadan-celebration-36587398/",
   "duration": 13,
   "width": 3840,
   "height": 2160,
   "user": {
    "name": "Cemrecan Yurtman"
   },
   "video_files": [
    {
     "file_type": "video/mp4",
     "width": 1920,
     "height": 1080,
     "link": "https://videos.pexels.com/video-files/36587398/15511705_1920_1080_25fps.mp4"
    }
   ]
  },
  {
   "id": 7126550,
   "url": "https://www.pexels.com/video/video-of-a-man-eating-7126550/",
   "duration": 10,
   "width": 2160,
   "height": 3840,
   "user": {
    "name": "Michael Burrows"
   },
   "video_files": [
    {
     "file_type": "video/mp4",
     "width": 1080,
     "height": 1920,
     "link": "https://videos.pexels.com/video-files/7126550/7126550-hd_1080_1920_24fps.mp4"
    }
   ]
  },
  {
   "id": 9096926,
   "url": "https://www.pexels.com/video/candle-light-on-a-dining-table-9096926/",
   "duration": 10,
   "width": 2160,
   "height": 3840,
   "user": {
    "name": "Timur Weber"
   },
   "video_files": [
    {
     "file_type": "video/mp4",
     "width": 1080,
     "height": 1920,
     "link": "https://videos.pexels.com/video-files/9096926/9096926-hd_1080_1920_24fps.mp4"
    }
   ]
  },
  {
   "id": 7126549,
   "url": "https://www.pexels.com/video/two-lantern-candle-lamp-on-the-table-7126549/",
   "duration": 10,
   "width": 2160,
   "height": 3840,
   "user": {
    "name": "Michael Burrows"
   },
   "video_files": [
    {
     "file_type": "video/mp4",
     "width": 1080,
     "height": 1920,
     "link": "https://videos.pexels.com/video-files/7126549/7126549-hd_1080_1920_24fps.mp4"
    }
   ]
  },
  {
   "id": 7126084,
   "url": "https://www.pexels.com/video/vintage-lamps-with-blinking-lights-7126084/",
   "duration": 10,
   "width": 2160,
   "height": 3840,
   "user": {
    "name": "Michael Burrows"
   },
   "video_files": [
    {
     "file_type": "video/mp4",
     "width": 1080,
     "height": 1920,
     "link": "https://videos.pexels.com/video-files/7126084/7126084-hd_1080_1920_24fps.mp4"
    }
   ]
  },
  {
   "id": 15245736,
   "url": "https://www.pexels.com/video/assorted-lanterns-hanging-15245736/",
   "duration": 20,
   "width": 3840,
   "height": 2160,
   "user": {
    "name": "khanhhoangminh"
   },
   "video_files": [
    {
     "file_type": "video/mp4",
     "width": 1920,
     "height": 1080,
     "link": "https://videos.pexels.com/video-files/15245736/15245736-hd_1920_1080_24fps.mp4"
    }
   ]
  },
  {
   "id": 36579901,
   "url": "https://www.pexels.com/video/ramadan-table-with-shared-meal-and-food-36579901/",
   "duration": 17,
   "width": 2160,
   "height": 3840,
   "user": {
    "name": "Orhan Pergel"
   },
   "video_files": [
    {
     "file_type": "video/mp4",
     "width": 1080,
     "height": 1920,
     "link": "https://videos.pexels.com/video-files/36579901/15509291_1080_1920_60fps.mp4"
    }
   ]
  },
  {
   "id": 36578304,
   "url": "https://www.pexels.com/video/festive-dinner-table-with-middle-eastern-cuisine-36578304/",
   "duration": 6,
   "width": 2160,
   "height": 3840,
   "user": {
    "name": "Orhan Pergel"
   },
   "video_files": [
    {
     "file_type": "video/mp4",
     "width": 1080,
     "height": 1920,
     "link": "https://videos.pexels.com/video-files/36578304/15509331_1080_1920_60fps.mp4"
    }
   ]
  }
 ],
 "incense": [
  {
   "id": 20719518,
   "url": "https://www.pexels.com/video/bakhoor-and-coffee-20719518/",
   "duration": 8,
   "width": 2160,
   "height": 3840,
   "user": {
    "name": "Ammad Rasool"
   },
   "video_files": [
    {
     "file_type": "video/mp4",
     "width": 1080,
     "height": 1920,
     "link": "https://videos.pexels.com/video-files/20719518/20719518-hd_1080_1920_25fps.mp4"
    }
   ]
  },
  {
   "id": 17928738,
   "url": "https://www.pexels.com/video/a-small-incense-holder-with-smoke-coming-out-of-it-17928738/",
   "duration": 30,
   "width": 1080,
   "height": 1920,
   "user": {
    "name": "‪yossrytop abdo‬‏"
   },
   "video_files": [
    {
     "file_type": "video/mp4",
     "width": 1080,
     "height": 1920,
     "link": "https://videos.pexels.com/video-files/17928738/17928738-hd_1080_1920_25fps.mp4"
    }
   ]
  },
  {
   "id": 7816005,
   "url": "https://www.pexels.com/video/burning-wood-on-a-stone-7816005/",
   "duration": 29,
   "width": 1080,
   "height": 1920,
   "user": {
    "name": "Mikhail Nilov"
   },
   "video_files": [
    {
     "file_type": "video/mp4",
     "width": 1080,
     "height": 1920,
     "link": "https://videos.pexels.com/video-files/7816005/7816005-hd_1080_1920_25fps.mp4"
    }
   ]
  },
  {
   "id": 8943205,
   "url": "https://www.pexels.com/video/smoke-from-a-burning-incense-8943205/",
   "duration": 7,
   "width": 1080,
   "height": 1920,
   "user": {
    "name": "Leeloo The First"
   },
   "video_files": [
    {
     "file_type": "video/mp4",
     "width": 1080,
     "height": 1920,
     "link": "https://videos.pexels.com/video-files/8943205/8943205-hd_1080_1920_30fps.mp4"
    }
   ]
  },
  {
   "id": 36705276,
   "url": "https://www.pexels.com/video/serene-oud-music-session-indoors-36705276/",
   "duration": 40,
   "width": 1920,
   "height": 1080,
   "user": {
    "name": "İrfan Simsar"
   },
   "video_files": [
    {
     "file_type": "video/mp4",
     "width": 1920,
     "height": 1080,
     "link": "https://videos.pexels.com/video-files/36705276/15558145_1920_1080_30fps.mp4"
    }
   ]
  },
  {
   "id": 17928486,
   "url": "https://www.pexels.com/video/censer-smoke-incense-17928486/",
   "duration": 21,
   "width": 1920,
   "height": 1080,
   "user": {
    "name": "‪yossrytop abdo‬‏"
   },
   "video_files": [
    {
     "file_type": "video/mp4",
     "width": 1920,
     "height": 1080,
     "link": "https://videos.pexels.com/video-files/17928486/17928486-hd_1920_1080_25fps.mp4"
    }
   ]
  }
 ],
 "heritage": [
  {
   "id": 37734489,
   "url": "https://www.pexels.com/video/majestic-desert-sunset-at-alula-s-elephant-rock-37734489/",
   "duration": 24,
   "width": 1080,
   "height": 1920,
   "user": {
    "name": "Enthusiastic Traveler"
   },
   "video_files": [
    {
     "file_type": "video/mp4",
     "width": 1080,
     "height": 1920,
     "link": "https://videos.pexels.com/video-files/37734489/16005705_1080_1920_30fps.mp4"
    }
   ]
  },
  {
   "id": 37734444,
   "url": "https://www.pexels.com/video/majestic-arabian-desert-road-in-saudi-arabia-37734444/",
   "duration": 41,
   "width": 1080,
   "height": 1920,
   "user": {
    "name": "Enthusiastic Traveler"
   },
   "video_files": [
    {
     "file_type": "video/mp4",
     "width": 1080,
     "height": 1920,
     "link": "https://videos.pexels.com/video-files/37734444/16005683_1080_1920_30fps.mp4"
    }
   ]
  },
  {
   "id": 34329524,
   "url": "https://www.pexels.com/video/dramatic-arabian-desert-landscape-shot-34329524/",
   "duration": 17,
   "width": 2160,
   "height": 3840,
   "user": {
    "name": "Grbr Snts"
   },
   "video_files": [
    {
     "file_type": "video/mp4",
     "width": 1080,
     "height": 1920,
     "link": "https://videos.pexels.com/video-files/34329524/14543342_1080_1920_30fps.mp4"
    }
   ]
  },
  {
   "id": 28219557,
   "url": "https://www.pexels.com/video/the-sun-is-setting-over-a-desert-with-rocks-28219557/",
   "duration": 8,
   "width": 1080,
   "height": 1920,
   "user": {
    "name": "Viktoria B."
   },
   "video_files": [
    {
     "file_type": "video/mp4",
     "width": 1080,
     "height": 1920,
     "link": "https://videos.pexels.com/video-files/28219557/12331303_1080_1920_60fps.mp4"
    }
   ]
  },
  {
   "id": 6358279,
   "url": "https://www.pexels.com/video/moving-cars-on-a-desert-6358279/",
   "duration": 15,
   "width": 1920,
   "height": 1080,
   "user": {
    "name": "Ibrahim Bennett"
   },
   "video_files": [
    {
     "file_type": "video/mp4",
     "width": 1920,
     "height": 1080,
     "link": "https://videos.pexels.com/video-files/6358279/6358279-hd_1920_1080_30fps.mp4"
    }
   ]
  },
  {
   "id": 4946072,
   "url": "https://www.pexels.com/video/natural-rock-formations-on-a-desert-4946072/",
   "duration": 11,
   "width": 1920,
   "height": 1080,
   "user": {
    "name": "Ibrahim Bennett"
   },
   "video_files": [
    {
     "file_type": "video/mp4",
     "width": 1920,
     "height": 1080,
     "link": "https://videos.pexels.com/video-files/4946072/4946072-hd_1920_1080_30fps.mp4"
    }
   ]
  },
  {
   "id": 18819906,
   "url": "https://www.pexels.com/video/alula-old-town-saudi-arabia-18819906/",
   "duration": 12,
   "width": 3840,
   "height": 2160,
   "user": {
    "name": "Aamir Somewhere"
   },
   "video_files": [
    {
     "file_type": "video/mp4",
     "width": 1920,
     "height": 1080,
     "link": "https://videos.pexels.com/video-files/18819906/18819906-hd_1920_1080_30fps.mp4"
    }
   ]
  },
  {
   "id": 11336190,
   "url": "https://www.pexels.com/video/old-castle-ruins-11336190/",
   "duration": 13,
   "width": 1080,
   "height": 1920,
   "user": {
    "name": "Kashif Shah"
   },
   "video_files": [
    {
     "file_type": "video/mp4",
     "width": 1080,
     "height": 1920,
     "link": "https://videos.pexels.com/video-files/11336190/11336190-hd_1080_1920_30fps.mp4"
    }
   ]
  },
  {
   "id": 30226373,
   "url": "https://www.pexels.com/video/majestic-fort-in-oman-at-sunset-30226373/",
   "duration": 30,
   "width": 2160,
   "height": 3840,
   "user": {
    "name": "Christine  Cleireny"
   },
   "video_files": [
    {
     "file_type": "video/mp4",
     "width": 1080,
     "height": 1920,
     "link": "https://videos.pexels.com/video-files/30226373/12959202_1080_1920_30fps.mp4"
    }
   ]
  },
  {
   "id": 15820146,
   "url": "https://www.pexels.com/video/low-angle-view-of-birds-flying-around-a-wind-tower-15820146/",
   "duration": 20,
   "width": 2082,
   "height": 3702,
   "user": {
    "name": "Mohammed Sahil  Sarafudeen"
   },
   "video_files": [
    {
     "file_type": "video/mp4",
     "width": 1080,
     "height": 1920,
     "link": "https://videos.pexels.com/video-files/15820146/15820146-hd_1080_1920_30fps.mp4"
    }
   ]
  },
  {
   "id": 29277974,
   "url": "https://www.pexels.com/video/charming-traditional-courtyard-in-dubai-29277974/",
   "duration": 9,
   "width": 2160,
   "height": 3840,
   "user": {
    "name": "Asi Si"
   },
   "video_files": [
    {
     "file_type": "video/mp4",
     "width": 1080,
     "height": 1920,
     "link": "https://videos.pexels.com/video-files/29277974/12628375_1080_1920_60fps.mp4"
    }
   ]
  },
  {
   "id": 39627844,
   "url": "https://www.pexels.com/video/exploring-traditional-adobe-brick-architecture-39627844/",
   "duration": 16,
   "width": 2160,
   "height": 3840,
   "user": {
    "name": "bobest Imagery"
   },
   "video_files": [
    {
     "file_type": "video/mp4",
     "width": 1080,
     "height": 1920,
     "link": "https://videos.pexels.com/video-files/39627844/16892270_1080_1920_30fps.mp4"
    }
   ]
  },
  {
   "id": 30795888,
   "url": "https://www.pexels.com/video/exploring-authentic-middle-eastern-bazaar-30795888/",
   "duration": 15,
   "width": 2160,
   "height": 3840,
   "user": {
    "name": "Asi Si"
   },
   "video_files": [
    {
     "file_type": "video/mp4",
     "width": 1080,
     "height": 1920,
     "link": "https://videos.pexels.com/video-files/30795888/13171597_1080_1920_30fps.mp4"
    }
   ]
  }
 ],
 "mosque": [
  {
   "id": 34903825,
   "url": "https://www.pexels.com/video/majestic-mosque-with-dome-and-minaret-under-clear-sky-34903825/",
   "duration": 20,
   "width": 1080,
   "height": 1920,
   "user": {
    "name": "Havvanur Akın"
   },
   "video_files": [
    {
     "file_type": "video/mp4",
     "width": 1080,
     "height": 1920,
     "link": "https://videos.pexels.com/video-files/34903825/14787048_1080_1920_30fps.mp4"
    }
   ]
  },
  {
   "id": 18468232,
   "url": "https://www.pexels.com/video/mosque-18468232/",
   "duration": 11,
   "width": 1920,
   "height": 1080,
   "user": {
    "name": "wajdi belghith"
   },
   "video_files": [
    {
     "file_type": "video/mp4",
     "width": 1920,
     "height": 1080,
     "link": "https://videos.pexels.com/video-files/18468232/18468232-hd_1920_1080_50fps.mp4"
    }
   ]
  },
  {
   "id": 10779949,
   "url": "https://www.pexels.com/video/clear-sky-over-mosque-10779949/",
   "duration": 16,
   "width": 3840,
   "height": 2160,
   "user": {
    "name": "Atif Dar"
   },
   "video_files": [
    {
     "file_type": "video/mp4",
     "width": 1920,
     "height": 1080,
     "link": "https://videos.pexels.com/video-files/10779949/10779949-hd_1920_1080_30fps.mp4"
    }
   ]
  },
  {
   "id": 35081957,
   "url": "https://www.pexels.com/video/modern-mosque-exterior-with-blue-sky-35081957/",
   "duration": 12,
   "width": 1512,
   "height": 2688,
   "user": {
    "name": "Sururi Ballıdağ Director"
   },
   "video_files": [
    {
     "file_type": "video/mp4",
     "width": 1080,
     "height": 1920,
     "link": "https://videos.pexels.com/video-files/35081957/14862053_1080_1920_30fps.mp4"
    }
   ]
  },
  {
   "id": 29803977,
   "url": "https://www.pexels.com/video/majestic-mosque-at-twilight-with-soaring-birds-29803977/",
   "duration": 25,
   "width": 1080,
   "height": 1920,
   "user": {
    "name": "Old Man TV"
   },
   "video_files": [
    {
     "file_type": "video/mp4",
     "width": 1080,
     "height": 1920,
     "link": "https://videos.pexels.com/video-files/29803977/12804254_1080_1920_60fps.mp4"
    }
   ]
  },
  {
   "id": 6576070,
   "url": "https://www.pexels.com/video/drone-footage-of-a-mosque-6576070/",
   "duration": 18,
   "width": 3840,
   "height": 2160,
   "user": {
    "name": "Khalid Khalitov"
   },
   "video_files": [
    {
     "file_type": "video/mp4",
     "width": 1920,
     "height": 1080,
     "link": "https://videos.pexels.com/video-files/6576070/6576070-hd_1920_1080_30fps.mp4"
    }
   ]
  },
  {
   "id": 7318023,
   "url": "https://www.pexels.com/video/mosque-in-the-middle-east-7318023/",
   "duration": 22,
   "width": 1920,
   "height": 1080,
   "user": {
    "name": "Pavel Danilyuk"
   },
   "video_files": [
    {
     "file_type": "video/mp4",
     "width": 1920,
     "height": 1080,
     "link": "https://videos.pexels.com/video-files/7318023/7318023-hd_1920_1080_30fps.mp4"
    }
   ]
  },
  {
   "id": 20671530,
   "url": "https://www.pexels.com/video/the-minaret-of-the-mosque-is-seen-in-this-photo-20671530/",
   "duration": 4,
   "width": 1920,
   "height": 1080,
   "user": {
    "name": "Orhan Pergel"
   },
   "video_files": [
    {
     "file_type": "video/mp4",
     "width": 1920,
     "height": 1080,
     "link": "https://videos.pexels.com/video-files/20671530/20671530-hd_1920_1080_60fps.mp4"
    }
   ]
  }
 ]
}


def topics(query):
    """The subjects a search names, in PATTERNS' order."""
    q = " ".join(str(query or "").split())
    return [t for t, pat in PATTERNS.items() if CLIPS.get(t) and pat.search(q)]


def clips(query, orientation=None, limit=6):
    """The picked clips for a search, as search results: those of the asked orientation first, at most `limit`."""
    seen, out = set(), []
    for t in topics(query):
        for c in CLIPS[t]:
            if c["id"] not in seen:
                seen.add(c["id"])
                out.append(c)

    def fits(c):
        w, h = c["width"], c["height"]
        shape = "portrait" if h > w * 1.1 else "landscape" if w > h * 1.1 else "square"
        return 0 if not orientation or shape == orientation else 1
    return sorted(out, key=fits)[:limit]
