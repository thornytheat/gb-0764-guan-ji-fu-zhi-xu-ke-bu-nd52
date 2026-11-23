import re

from app.problem import DeskError

PAGE_SYNTAX = re.compile(r'[1-9][0-9]{0,6}(?:-[1-9][0-9]{0,6})?(?:\s*;\s*[1-9][0-9]{0,6}(?:-[1-9][0-9]{0,6})?)*')


def merge(intervals):
    merged = []
    for start,end in sorted(intervals):
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(end,merged[-1][1])
        else:
            merged.append([start,end])
    return merged


def normalize(text):
    intervals = []
    for expression in text.split(';'):
        numbers = list(map(int, expression.split('-')))
        intervals.append((numbers[0], numbers[-1]+1))
    return merge(intervals)


def parse(text):
    if not isinstance(text,str) or not text or len(text) > 512 or not PAGE_SYNTAX.fullmatch(text):
        raise DeskError('INVALID')
    for expression in text.split(';'):
        numbers = [int(number) for number in expression.split('-')]
        if numbers[0] > numbers[-1]:
            raise DeskError('INVALID')
    return normalize(text)


def pages_in(spans):
    return sum(end-start for start,end in spans)


def union(left, right):
    return merge([list(span) for span in left]+[list(span) for span in right])


def intersect(left, right):
    result = []
    for start,end in left:
        for other_start,other_end in right:
            low,high = max(start,other_start),min(end,other_end)
            if low < high:
                result.append([low,high])
    return merge(result)


def subtract(left, right):
    result = []
    for start,end in left:
        pieces = [[start,end]]
        for cut_start,cut_end in right:
            remainder = []
            for piece_start,piece_end in pieces:
                if cut_end <= piece_start or cut_start >= piece_end:
                    remainder.append([piece_start,piece_end])
                    continue
                if piece_start < cut_start:
                    remainder.append([piece_start,cut_start])
                if cut_end < piece_end:
                    remainder.append([cut_end,piece_end])
            pieces = remainder
        result.extend(pieces)
    return merge(result)


def split_limit(intervals, first, last, allowance):
    allowed, out_of_range, exhausted = [], [], []
    for start,end in intervals:
        low,high = max(first,start),min(last+1,end)
        if low >= high:
            out_of_range.append([start,end])
            continue
        if start < low:
            out_of_range.append([start,low])
        if high < end:
            out_of_range.append([high,end])
        taken = min(allowance, high-low)
        if taken:
            allowed.append([low,low+taken])
        if low+taken < high:
            exhausted.append([low+taken,high])
        allowance -= taken
    return allowed, out_of_range, exhausted
