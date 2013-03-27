from collections import namedtuple
import os
import sys
import urllib
import codecs
import urlparse
import csv
import tinycss

from lxml import etree
from inlinestyler.inlinestyler_cssselect import CSSSelector
from cssselect import parse, HTMLTranslator, ExpressionError

stylevalue = namedtuple('InlineStyle', 'content priority')

class Conversion:
    def __init__(self):
        self.CSSErrors=[]
        self.CSSUnsupportErrors=dict()
        self.supportPercentage=100
        self.convertedHTML=""

    def perform(self,document,sourceHTML,sourceURL):
        aggregateCSS="";

        # retrieve CSS rel links from html pasted and aggregate into one string
        CSSRelSelector = CSSSelector("link[rel=stylesheet],link[rel=StyleSheet],link[rel=STYLESHEET]")
        matching = CSSRelSelector.evaluate(document)
        for element in matching:
            try:
                csspath=element.get("href")
                if len(sourceURL):
                    if element.get("href").lower().find("http://",0) < 0:
                        parsedUrl=urlparse.urlparse(sourceURL);
                        csspath=urlparse.urljoin(parsedUrl.scheme+"://"+parsedUrl.hostname, csspath)
                f=urllib.urlopen(csspath)
                aggregateCSS+=''.join(f.read())
                element.getparent().remove(element)
            except:
                raise IOError('The stylesheet '+element.get("href")+' could not be found')

        #include inline style elements
        CSSStyleSelector = CSSSelector("style,Style")
        matching = CSSStyleSelector.evaluate(document)
        for element in matching:
            aggregateCSS+=element.text
            element.getparent().remove(element)

        #convert  document to a style dictionary compatible with etree
        styledict = self.getView(document, aggregateCSS)

        #set inline style attribute if not one of the elements not worth styling
        ignoreList=['html','head','title','meta','link','script']
        for element, styles in styledict.items():
            if element.tag not in ignoreList:
                inlineStyle = ';'.join([prop + ":" + value.content for prop, value in styles.items()])
                element.set('style', inlineStyle)

        #convert tree back to plain text html
        self.convertedHTML = etree.tostring(document, method="xml", pretty_print=True,encoding='UTF-8')
        self.convertedHTML= self.convertedHTML.replace('&#13;', '') #tedious raw conversion of line breaks.

        return self

    def styleattribute(self,element):
        """
          returns css.CSSStyleDeclaration of inline styles, for html: @style
          """
        parser = tinycss.make_parser('page3')
        cssText = element.get('style')
        if cssText:
            return parser.parse_style_attr(cssText)
        else:
            return []

    def getView(self, document, css):

        view = {}
        specificities = {}
        supportratios={}
        supportFailRate=0
        supportTotalRate=0;
        compliance=dict()

        #load CSV containing css property client support into dict
        mycsv = csv.DictReader(open(os.path.join(os.path.dirname(__file__), "css_compliance.csv")), delimiter=',')

        for row in mycsv:
            #count clients so we can calculate an overall support percentage later
            clientCount=len(row)
            compliance[row['property'].strip()]=dict(row);

        #decrement client count to account for first col which is property name
        clientCount-=1

        #sheet = csscombine(path="http://www.torchbox.com/css/front/import.css")
        parser = tinycss.make_parser('page3')
        sheet = parser.parse_stylesheet(unicode(css))

        rules = (rule for rule in sheet.rules if not rule.at_keyword)
        for rule in rules:
            selectors = parse(rule.selector.as_css())
            for selector in selectors:
                try:
                    xpath_string = HTMLTranslator().selector_to_xpath(selector)
                    matching = etree.XPath(xpath_string)(document)

                    for element in matching:
                        # add styles for all matching DOM elements
                        if element not in view:
                            # add initial
                            view[element] = {}
                            specificities[element] = {}

                            # add inline style if present
                            inlinestyletext= element.get('style')
                            if inlinestyletext:
                                inlinestyle, _=parser.parse_style_attr(inlinestyletext)
                            else:
                                inlinestyle = None
                            if inlinestyle:
                                for p in inlinestyle:
                                    # set inline style specificity
                                    view[element][p.name] = stylevalue(p.value.as_css(), p.priority)
                                    specificities[element][p.name] = (1,0,0,0)

                        for p in rule.declarations:
                            #create supportratio dic item for this property
                            if p.name not in supportratios:
                                supportratios[p.name]={'usage':0,'failedClients':0}
                            #increment usage
                            supportratios[p.name]['usage']+=1

                            try:
                                if not p.name in self.CSSUnsupportErrors:
                                    for client, support in compliance[p.name].items():
                                        if support == "N" or support=="P":
                                            #increment client failure count for this property
                                            supportratios[p.name]['failedClients']+=1
                                            if not p.name in self.CSSUnsupportErrors:
                                                if support == "P":
                                                    self.CSSUnsupportErrors[p.name]=[client + ' (partial support)']
                                                else:
                                                    self.CSSUnsupportErrors[p.name]=[client]
                                            else:
                                                if support == "P":
                                                    self.CSSUnsupportErrors[p.name].append(client + ' (partial support)')
                                                else:
                                                    self.CSSUnsupportErrors[p.name].append(client)

                            except KeyError:
                                pass

                            # update styles
                            specificity = (0,) + selector.specificity()[:3]
                            if p.name not in view[element]:
                                view[element][p.name] = stylevalue(p.value.as_css(), p.priority)
                                specificities[element][p.name] = specificity
                            else:
                                sameprio = (p.priority == view[element][p.name][1])
                                if not sameprio and bool(p.priority) or (sameprio and specificity >= specificities[element][p.name]):
                                    # later, more specific or higher prio
                                    view[element][p.name] = stylevalue(p.value.as_css(), p.priority)

                except ExpressionError:
                    if str(sys.exc_info()[1]) not in self.CSSErrors:
                        self.CSSErrors.append(str(sys.exc_info()[1]))
                    pass

        for props, propvals in supportratios.items():
            supportFailRate+=(propvals['usage']) * int(propvals['failedClients'])
            supportTotalRate+=int(propvals['usage']) * clientCount

        if(supportFailRate and supportTotalRate):
            self.supportPercentage= 100- ((float(supportFailRate)/float(supportTotalRate)) * 100)
        return view

class MyURLopener(urllib.FancyURLopener):
    http_error_default = urllib.URLopener.http_error_default
